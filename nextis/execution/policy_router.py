"""Policy router — dispatches assembly steps to primitives or learned policies.

For primitive-type steps, calls the appropriate function from PrimitiveLibrary.
For policy-type steps, loads a trained checkpoint via PolicyLoader and runs
inference. Falls back to failure (triggering human intervention) when no
trained policy exists.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from nextis.assembly.models import AssemblyStep
from nextis.control.primitives import PrimitiveLibrary
from nextis.execution.types import StepResult
from nextis.learning.policy_loader import PolicyLoader

logger = logging.getLogger(__name__)


class PolicyRouter:
    """Routes assembly steps to the appropriate execution handler.

    Args:
        primitive_library: PrimitiveLibrary for dispatching primitive steps.
        robot: Connected follower robot instance (passed to primitives).
        policy_loader: PolicyLoader for loading trained checkpoints.
        assembly_id: Active assembly ID (needed for policy lookup).
    """

    def __init__(
        self,
        primitive_library: PrimitiveLibrary | None = None,
        robot: Any = None,
        policy_loader: PolicyLoader | None = None,
        assembly_id: str = "",
    ) -> None:
        self._primitives = primitive_library or PrimitiveLibrary()
        self._robot = robot
        self._policy_loader = policy_loader or PolicyLoader()
        self._assembly_id = assembly_id

    async def dispatch(self, step: AssemblyStep) -> StepResult:
        """Dispatch a step to the appropriate handler.

        Args:
            step: The assembly step to execute.

        Returns:
            StepResult with success/failure and timing.
        """
        start_ms = time.monotonic() * 1000

        if step.handler == "primitive":
            return await self._run_primitive(step, start_ms)
        if step.handler == "policy":
            return await self._run_policy(step, start_ms)
        if step.handler == "rl_finetune":
            return await self._run_rl_policy(step, start_ms)

        logger.error("Unknown handler type '%s' for step %s", step.handler, step.id)
        return StepResult(
            success=False,
            duration_ms=time.monotonic() * 1000 - start_ms,
            handler_used=step.handler,
            error_message=f"Unknown handler: {step.handler}",
        )

    async def _run_primitive(self, step: AssemblyStep, start_ms: float) -> StepResult:
        """Execute a primitive-type step."""
        if not step.primitive_type:
            return StepResult(
                success=False,
                duration_ms=time.monotonic() * 1000 - start_ms,
                handler_used="primitive",
                error_message=f"Step {step.id} has no primitive_type set",
            )

        try:
            result = await self._primitives.run(
                name=step.primitive_type,
                robot=self._robot,
                params=step.primitive_params,
            )
            return StepResult(
                success=result.success,
                duration_ms=result.duration_ms,
                handler_used="primitive",
                error_message=result.error_message,
                actual_force=result.actual_force,
                actual_position=result.actual_position,
                force_history=result.force_history,
            )
        except Exception as e:
            logger.error("Primitive '%s' failed on step %s: %s", step.primitive_type, step.id, e)
            return StepResult(
                success=False,
                duration_ms=time.monotonic() * 1000 - start_ms,
                handler_used="primitive",
                error_message=str(e),
            )

    async def _run_policy(self, step: AssemblyStep, start_ms: float) -> StepResult:
        """Execute a policy-type step using a trained checkpoint.

        Loads the policy via PolicyLoader, then runs an inference loop
        at 50 Hz for ``chunk_size`` steps, sending actions to the robot
        if one is connected.
        """
        policy = self._policy_loader.load(self._assembly_id, step.id)
        if policy is None:
            logger.warning(
                "No trained policy for step '%s' (assembly=%s) — failing",
                step.id,
                self._assembly_id,
            )
            return StepResult(
                success=False,
                duration_ms=time.monotonic() * 1000 - start_ms,
                handler_used="policy",
                error_message=f"No trained policy for step {step.id}",
            )

        logger.info(
            "Running policy inference for step %s (chunk_size=%d)",
            step.id,
            policy.chunk_size,
        )

        try:
            # Use MockRobot for inference when no real robot is connected.
            robot = self._robot
            if robot is None:
                from nextis.hardware.mock import MockRobot

                robot = MockRobot()

            obs = robot.get_observation()
            actions = policy.predict(obs)
            action_keys = policy.joint_keys or sorted(obs.keys())

            for i in range(policy.chunk_size):
                action = actions[min(i, len(actions) - 1)]
                action_dict = dict(zip(action_keys, action, strict=False))
                robot.send_action(action_dict)
                await asyncio.sleep(1 / 50)  # 50 Hz control rate

            return StepResult(
                success=True,
                duration_ms=time.monotonic() * 1000 - start_ms,
                handler_used="policy",
            )

        except Exception as e:
            logger.error("Policy inference failed on step %s: %s", step.id, e)
            return StepResult(
                success=False,
                duration_ms=time.monotonic() * 1000 - start_ms,
                handler_used="policy",
                error_message=str(e),
            )

    async def _run_rl_policy(self, step: AssemblyStep, start_ms: float) -> StepResult:
        """Execute a step using an RL-finetuned SAC policy.

        Loads the SAC agent from ``policy_rl.pt``. If no RL checkpoint exists,
        falls back to BC inference via ``_run_policy``.
        """
        from pathlib import Path

        rl_ckpt = Path("data/policies") / self._assembly_id / step.id / "policy_rl.pt"

        if not rl_ckpt.exists():
            logger.info(
                "No RL checkpoint for step %s, falling back to BC policy",
                step.id,
            )
            return await self._run_policy(step, start_ms)

        try:
            import numpy as np

            from nextis.control.motion_helpers import joints_to_action, obs_to_joints
            from nextis.learning.sac import SACAgent

            agent = SACAgent.load(rl_ckpt)

            robot = self._robot
            if robot is None:
                from nextis.hardware.mock import MockRobot

                robot = MockRobot()

            logger.info("Running RL policy inference for step %s", step.id)

            # Run deterministic inference for a fixed horizon
            max_steps = 100
            for _ in range(max_steps):
                obs = robot.get_observation()
                obs_array = np.array(obs_to_joints(obs), dtype=np.float32)
                action = agent.select_action(obs_array, deterministic=True)
                robot.send_action(joints_to_action(action.tolist()))
                await asyncio.sleep(1 / 50)

            return StepResult(
                success=True,
                duration_ms=time.monotonic() * 1000 - start_ms,
                handler_used="rl_finetune",
            )

        except Exception as e:
            logger.error("RL policy inference failed on step %s: %s", step.id, e)
            return StepResult(
                success=False,
                duration_ms=time.monotonic() * 1000 - start_ms,
                handler_used="rl_finetune",
                error_message=str(e),
            )
