"""Reward computer for per-step RL fine-tuning.

Converts StepVerifier outputs and step telemetry into per-timestep scalar
rewards. Provides dense shaping rewards (position/force proximity) plus
sparse terminal rewards from the verification system.
"""

from __future__ import annotations

import logging

import numpy as np

from nextis.assembly.models import AssemblyStep
from nextis.perception.types import ExecutionData, VerificationResult
from nextis.perception.verifier import StepVerifier

logger = logging.getLogger(__name__)


class StepRewardComputer:
    """Computes dense and terminal rewards for a specific assembly step.

    Uses the step's success_criteria and primitive_params to compute shaped
    rewards from force/position telemetry, plus a sparse terminal reward
    from the StepVerifier.

    Args:
        step: The assembly step defining success criteria.
        verifier: StepVerifier for terminal success/failure determination.
    """

    def __init__(self, step: AssemblyStep, verifier: StepVerifier) -> None:
        self._step = step
        self._verifier = verifier
        self._prev_action: np.ndarray | None = None

        # Extract target pose from step params if available
        self._target_pose: list[float] | None = None
        if step.primitive_params and "target_pose" in step.primitive_params:
            self._target_pose = step.primitive_params["target_pose"]

        # Extract force threshold from success criteria
        self._force_threshold: float | None = None
        criteria_type = step.success_criteria.type if step.success_criteria else None
        if criteria_type == "force_threshold" and step.success_criteria.threshold:
            self._force_threshold = step.success_criteria.threshold

    def compute_timestep_reward(
        self,
        obs: np.ndarray,
        action: np.ndarray,
        torques: list[float],
        force_history: list[float],
    ) -> float:
        """Compute dense shaping reward for a single timestep.

        Shaping rewards are small relative to the terminal reward, summing
        to less than 1.0 per episode in typical use.

        Args:
            obs: Current joint positions as numpy array.
            action: Action taken as numpy array.
            torques: Current joint torques.
            force_history: Accumulated force magnitudes so far.

        Returns:
            Dense reward scalar.
        """
        reward = 0.0

        # Position shaping: negative L2 distance to target
        if self._target_pose is not None:
            target = np.array(self._target_pose[: len(obs)], dtype=np.float32)
            distance = float(np.linalg.norm(obs - target))
            reward += -0.1 * distance

        # Force shaping: reward proportional to peak_force / threshold
        if self._force_threshold is not None and torques:
            peak = max(abs(t) for t in torques)
            ratio = min(peak / self._force_threshold, 1.0)
            reward += 0.1 * ratio

        # Smoothness: penalize large action deltas (jerk minimization)
        if self._prev_action is not None:
            delta = float(np.max(np.abs(action - self._prev_action)))
            reward += -0.01 * delta
        self._prev_action = action.copy()

        return reward

    async def compute_terminal_reward(self, exec_data: ExecutionData) -> float:
        """Compute sparse terminal reward using StepVerifier.

        Args:
            exec_data: Telemetry snapshot from step execution.

        Returns:
            +10.0 scaled by confidence if passed, -1.0 scaled by confidence
            if failed.
        """
        result: VerificationResult = await self._verifier.verify(
            self._step, exec_data
        )

        terminal = 10.0 * result.confidence if result.passed else -1.0 * result.confidence

        logger.debug(
            "Terminal reward for step %s: %.2f (passed=%s, confidence=%.2f)",
            self._step.id,
            terminal,
            result.passed,
            result.confidence,
        )
        return terminal

    def reset(self) -> None:
        """Reset per-episode state (previous action tracker)."""
        self._prev_action = None
