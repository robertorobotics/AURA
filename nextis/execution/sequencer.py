"""Assembly execution sequencer — state machine that walks the assembly graph.

The Sequencer iterates through the assembly step_order, dispatching each step
to the PolicyRouter (which routes to primitives or policies), handling retries,
and escalating to human intervention when retries are exhausted. State changes
are emitted via a callback for WebSocket push to the frontend.

Reference: HIL state machine pattern from Nextis_Bridge/app/core/hil_service.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from enum import Enum  # noqa: UP042

from nextis.analytics.store import AnalyticsStore
from nextis.api.schemas import ExecutionState, StepRuntimeState
from nextis.assembly.models import AssemblyGraph, AssemblyStep
from nextis.errors import AssemblyError
from nextis.execution.policy_router import PolicyRouter
from nextis.execution.types import StepResult
from nextis.perception.types import ExecutionData
from nextis.perception.verifier import StepVerifier

logger = logging.getLogger(__name__)


class SequencerState(str, Enum):  # noqa: UP042
    """Internal states for the execution sequencer."""

    IDLE = "idle"
    RUNNING = "running"
    STEP_ACTIVE = "step_active"
    STEP_COMPLETE = "step_complete"
    PAUSED = "paused"
    WAITING_FOR_HUMAN = "teaching"
    COMPLETE = "complete"
    ERROR = "error"


# Maps internal states to the API phase string the frontend expects.
_PHASE_MAP: dict[SequencerState, str] = {
    SequencerState.IDLE: "idle",
    SequencerState.RUNNING: "running",
    SequencerState.STEP_ACTIVE: "running",
    SequencerState.STEP_COMPLETE: "running",
    SequencerState.PAUSED: "paused",
    SequencerState.WAITING_FOR_HUMAN: "teaching",
    SequencerState.COMPLETE: "complete",
    SequencerState.ERROR: "error",
}


class Sequencer:
    """State machine that walks the assembly graph step by step.

    Args:
        graph: The assembly definition to execute.
        on_state_change: Called with an ExecutionState on every transition.
        router: PolicyRouter for dispatching steps to primitives/policies.
    """

    def __init__(
        self,
        graph: AssemblyGraph,
        on_state_change: Callable[[ExecutionState], None],
        router: PolicyRouter | None = None,
        analytics: AnalyticsStore | None = None,
        verifier: StepVerifier | None = None,
        demo_mode: bool = False,
    ) -> None:
        if not graph.step_order:
            raise AssemblyError(f"Assembly '{graph.id}' has no steps to execute")

        self._graph = graph
        self._on_state_change = on_state_change
        self._router = router or PolicyRouter()
        self._analytics = analytics
        self._verifier = verifier
        self._demo_mode = demo_mode

        self._state = SequencerState.IDLE
        self._step_index: int = 0
        self._step_states: dict[str, StepRuntimeState] = {}
        self._current_attempt: int = 1
        self._run_number: int = 0
        self._start_time: float | None = None

        self._task: asyncio.Task[None] | None = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused initially
        self._human_done_event = asyncio.Event()
        self._stop_requested = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def state(self) -> SequencerState:
        """Current sequencer state."""
        return self._state

    @property
    def current_step(self) -> AssemblyStep | None:
        """The step currently being executed, or None if idle/complete."""
        if self._state in (SequencerState.IDLE, SequencerState.COMPLETE):
            return None
        if 0 <= self._step_index < len(self._graph.step_order):
            step_id = self._graph.step_order[self._step_index]
            return self._graph.steps.get(step_id)
        return None

    async def start(self) -> None:
        """Begin executing the assembly graph from the first step."""
        if self._state not in (SequencerState.IDLE, SequencerState.COMPLETE, SequencerState.ERROR):
            logger.warning("Cannot start: sequencer is in state %s", self._state)
            return

        self._stop_requested = False
        self._step_index = 0
        self._current_attempt = 1
        self._run_number += 1
        self._start_time = time.time() * 1000
        self._pause_event.set()
        self._human_done_event.clear()

        # Initialize all step states to pending
        self._step_states = {sid: StepRuntimeState(step_id=sid) for sid in self._graph.step_order}

        self._state = SequencerState.RUNNING
        self._emit()

        self._task = asyncio.create_task(self._run())
        logger.info(
            "Sequencer started: assembly=%s run=%d steps=%d demo_mode=%s",
            self._graph.id,
            self._run_number,
            len(self._graph.step_order),
            self._demo_mode,
        )

    async def pause(self) -> None:
        """Pause execution. The current step finishes before pausing."""
        if self._state not in (SequencerState.STEP_ACTIVE, SequencerState.RUNNING):
            logger.warning("Cannot pause: sequencer is in state %s", self._state)
            return
        self._pause_event.clear()
        self._state = SequencerState.PAUSED
        self._emit()
        logger.info("Sequencer paused at step %d", self._step_index)

    async def resume(self) -> None:
        """Resume execution after a pause."""
        if self._state != SequencerState.PAUSED:
            logger.warning("Cannot resume: sequencer is in state %s", self._state)
            return
        self._state = SequencerState.STEP_ACTIVE
        self._pause_event.set()
        self._emit()
        logger.info("Sequencer resumed at step %d", self._step_index)

    async def stop(self) -> None:
        """Stop execution and reset to idle."""
        self._stop_requested = True
        self._pause_event.set()  # Unblock if paused
        self._human_done_event.set()  # Unblock if waiting for human

        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        self._state = SequencerState.IDLE
        self._emit()
        logger.info("Sequencer stopped")

    async def complete_human_step(self, success: bool = True) -> None:
        """Signal that a human has completed the current step.

        Args:
            success: Whether the human successfully completed the step.
        """
        if self._state != SequencerState.WAITING_FOR_HUMAN:
            logger.warning("Not waiting for human: state is %s", self._state)
            return

        step_id = self._graph.step_order[self._step_index]
        if success:
            now = time.time() * 1000
            self._step_states[step_id] = StepRuntimeState(
                step_id=step_id,
                status="success",
                attempt=self._current_attempt,
                start_time=self._step_states[step_id].start_time,
                end_time=now,
                duration_ms=now - (self._step_states[step_id].start_time or now),
            )
            logger.info("Human completed step %s successfully", step_id)
            if self._analytics is not None:
                self._analytics.record_step_result(
                    assembly_id=self._graph.id,
                    step_id=step_id,
                    success=True,
                    duration_ms=self._step_states[step_id].duration_ms or 0.0,
                    attempt=self._current_attempt,
                )
        else:
            self._step_states[step_id] = StepRuntimeState(
                step_id=step_id,
                status="failed",
                attempt=self._current_attempt,
                start_time=self._step_states[step_id].start_time,
                end_time=time.time() * 1000,
            )
            logger.warning("Human marked step %s as failed", step_id)
            if self._analytics is not None:
                self._analytics.record_step_result(
                    assembly_id=self._graph.id,
                    step_id=step_id,
                    success=False,
                    duration_ms=0.0,
                    attempt=self._current_attempt,
                )

        self._human_done_event.set()

    def get_execution_state(self) -> ExecutionState:
        """Build an ExecutionState snapshot for the API and WebSocket."""
        now = time.time() * 1000
        elapsed = (now - self._start_time) if self._start_time else 0.0

        current_step_id = None
        if self._state not in (
            SequencerState.IDLE,
            SequencerState.COMPLETE,
        ) and 0 <= self._step_index < len(self._graph.step_order):
            current_step_id = self._graph.step_order[self._step_index]

        completed = sum(1 for s in self._step_states.values() if s.status == "success")
        attempted = sum(1 for s in self._step_states.values() if s.status in ("success", "failed"))
        rate = completed / attempted if attempted else 0.0

        return ExecutionState(
            phase=_PHASE_MAP[self._state],
            assembly_id=self._graph.id,
            current_step_id=current_step_id,
            step_states=dict(self._step_states),
            run_number=self._run_number,
            start_time=self._start_time,
            elapsed_ms=elapsed,
            overall_success_rate=rate,
        )

    # ------------------------------------------------------------------
    # Internal execution loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Main execution loop — walks the assembly graph step by step."""
        try:
            for i, step_id in enumerate(self._graph.step_order):
                if self._stop_requested:
                    break

                self._step_index = i
                step = self._graph.steps.get(step_id)
                if not step:
                    logger.error("Step %s not found in assembly graph", step_id)
                    continue

                self._current_attempt = 1
                max_attempts = step.max_retries + 1

                # Mark step as running
                self._step_states[step_id] = StepRuntimeState(
                    step_id=step_id,
                    status="running",
                    attempt=1,
                    start_time=time.time() * 1000,
                )
                self._state = SequencerState.STEP_ACTIVE
                self._emit()

                # Retry loop
                success = False
                while self._current_attempt <= max_attempts:
                    # Wait if paused
                    await self._pause_event.wait()
                    if self._stop_requested:
                        break

                    result = await self._dispatch_step(step)

                    # Verify step outcome if dispatch reported success
                    if result.success and self._verifier:
                        # Convert per-joint torque history to magnitude series
                        magnitudes = [
                            max(abs(t) for t in tick) if tick else 0.0
                            for tick in result.force_history
                        ]
                        exec_data = ExecutionData(
                            final_position=result.actual_position,
                            force_history=magnitudes,
                            peak_force=result.actual_force,
                            final_force=magnitudes[-1] if magnitudes else 0.0,
                            duration_ms=result.duration_ms,
                        )
                        vr = await self._verifier.verify(step, exec_data)
                        if not vr.passed:
                            result = StepResult(
                                success=False,
                                duration_ms=result.duration_ms,
                                handler_used=result.handler_used,
                                error_message=f"Verification failed: {vr.detail}",
                            )

                    # Record analytics for every dispatch attempt
                    if self._analytics is not None:
                        self._analytics.record_step_result(
                            assembly_id=self._graph.id,
                            step_id=step_id,
                            success=result.success,
                            duration_ms=result.duration_ms,
                            attempt=self._current_attempt,
                        )

                    if result.success:
                        now = time.time() * 1000
                        self._step_states[step_id] = StepRuntimeState(
                            step_id=step_id,
                            status="success",
                            attempt=self._current_attempt,
                            start_time=self._step_states[step_id].start_time,
                            end_time=now,
                            duration_ms=result.duration_ms,
                        )
                        self._state = SequencerState.STEP_COMPLETE
                        self._emit()
                        success = True
                        logger.info(
                            "Step %s succeeded (attempt %d, %.0fms)",
                            step_id,
                            self._current_attempt,
                            result.duration_ms,
                        )
                        break

                    # Step failed
                    if self._current_attempt < max_attempts:
                        self._current_attempt += 1
                        self._step_states[step_id] = StepRuntimeState(
                            step_id=step_id,
                            status="retrying",
                            attempt=self._current_attempt,
                            start_time=time.time() * 1000,
                        )
                        self._emit()
                        logger.warning(
                            "Step %s failed (attempt %d/%d): %s",
                            step_id,
                            self._current_attempt - 1,
                            max_attempts,
                            result.error_message,
                        )
                        await asyncio.sleep(0.5)
                    else:
                        # Exhausted retries — escalate to human
                        self._step_states[step_id] = StepRuntimeState(
                            step_id=step_id,
                            status="human",
                            attempt=self._current_attempt,
                            start_time=self._step_states[step_id].start_time,
                        )
                        self._state = SequencerState.WAITING_FOR_HUMAN
                        self._emit()
                        logger.warning(
                            "Step %s exhausted %d retries — waiting for human",
                            step_id,
                            max_attempts,
                        )

                        # Block until human completes or stop is requested
                        self._human_done_event.clear()
                        await self._human_done_event.wait()
                        if self._stop_requested:
                            break
                        success = True
                        break

                if self._stop_requested:
                    break
                if not success:
                    self._state = SequencerState.ERROR
                    self._emit()
                    break

            # Finished
            if not self._stop_requested and self._state != SequencerState.ERROR:
                self._state = SequencerState.COMPLETE
                self._emit()
                logger.info("Assembly execution complete: %s", self._graph.id)

        except asyncio.CancelledError:
            logger.info("Sequencer task cancelled")
        except Exception as e:
            logger.error("Sequencer error: %s", e, exc_info=True)
            self._state = SequencerState.ERROR
            self._emit()

    async def _dispatch_step(self, step: AssemblyStep) -> StepResult:
        """Dispatch a single step to the policy router."""
        if self._demo_mode:
            await asyncio.sleep(0.3)
            return StepResult(success=True, duration_ms=300.0, handler_used="demo")
        return await self._router.dispatch(step)

    def _emit(self) -> None:
        """Push state change to the callback."""
        try:
            state = self.get_execution_state()
            self._on_state_change(state)
        except Exception as e:
            logger.error("State change callback failed: %s", e)
