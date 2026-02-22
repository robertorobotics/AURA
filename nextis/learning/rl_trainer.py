"""Per-step HIL-SERL fine-tuning loop.

Runs SAC-based online reinforcement learning on a real or mock robot for
a single assembly step. Human interventions via the leader arm are detected
and stored with priority in the replay buffer (RLPD component). Rewards
come from the existing StepVerifier checkers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from nextis.assembly.models import AssemblyStep
from nextis.control.intervention import InterventionDetector
from nextis.control.motion_helpers import (
    JOINT_COUNT,
    joints_to_action,
    obs_to_joints,
    read_torques_list,
)
from nextis.learning.policy_loader import Policy
from nextis.learning.replay_buffer import ReplayBuffer, Transition
from nextis.learning.reward import StepRewardComputer
from nextis.learning.sac import SACAgent, SACConfig
from nextis.perception.types import ExecutionData
from nextis.perception.verifier import StepVerifier

logger = logging.getLogger(__name__)


@dataclass
class RLConfig:
    """Configuration for RL fine-tuning.

    Attributes:
        max_episodes: Maximum number of RL episodes.
        max_steps_per_episode: Maximum timesteps per episode.
        control_hz: Action frequency during RL rollouts.
        warmup_transitions: Minimum buffer size before updating.
        updates_per_step: Gradient updates per environment step (UTD ratio).
        intervention_velocity_threshold: Leader velocity threshold for intervention.
        movement_scale: Safety limiter on action magnitude.
        success_rate_threshold: Stop fine-tuning when rolling success rate exceeds this.
        save_interval_episodes: Checkpoint every N episodes.
    """

    max_episodes: int = 50
    max_steps_per_episode: int = 200
    control_hz: int = 50
    warmup_transitions: int = 100
    updates_per_step: int = 1
    intervention_velocity_threshold: float = 0.05
    movement_scale: float = 0.5
    success_rate_threshold: float = 0.8
    save_interval_episodes: int = 10


@dataclass
class RLProgress:
    """Progress update emitted during RL training.

    Attributes:
        episode: Current episode number (0-indexed).
        total_episodes: Maximum episodes configured.
        episode_reward: Total reward accumulated in this episode.
        success: Whether the episode succeeded per StepVerifier.
        intervention_rate: Fraction of timesteps with human intervention.
        critic_loss: Average critic loss from SAC updates.
        actor_loss: Average actor loss from SAC updates.
        buffer_size: Current replay buffer size.
    """

    episode: int
    total_episodes: int
    episode_reward: float
    success: bool
    intervention_rate: float
    critic_loss: float
    actor_loss: float
    buffer_size: int


@dataclass
class RLResult:
    """Final result of RL fine-tuning.

    Attributes:
        checkpoint_path: Path to saved RL policy checkpoint.
        episodes_trained: Number of episodes completed.
        final_success_rate: Rolling success rate at termination.
        total_interventions: Total timesteps with human intervention.
    """

    checkpoint_path: Path
    episodes_trained: int
    final_success_rate: float
    total_interventions: int


class StepRLTrainer:
    """Per-step HIL-SERL fine-tuning loop.

    Runs on the real robot (or MockRobot for testing). Requires a
    BC-pretrained policy for warm-starting SAC, a connected robot and
    leader arm, and the assembly step definition for reward computation.

    Args:
        robot: Connected follower robot.
        leader: Connected leader arm (for human interventions).
        step: The assembly step to fine-tune.
        assembly_id: Assembly identifier (for checkpoint paths).
        bc_policy: BC-pretrained policy to initialize from, or None.
        verifier: StepVerifier for terminal reward.
        config: RL hyperparameters.
        on_progress: Optional callback for per-episode progress updates.
        policies_dir: Root directory for policy checkpoints.
    """

    def __init__(
        self,
        robot: Any,
        leader: Any,
        step: AssemblyStep,
        assembly_id: str,
        bc_policy: Policy | None = None,
        verifier: StepVerifier | None = None,
        config: RLConfig | None = None,
        on_progress: Callable[[RLProgress], None] | None = None,
        policies_dir: str = "data/policies",
    ) -> None:
        self._robot = robot
        self._leader = leader
        self._step = step
        self._assembly_id = assembly_id
        self._bc_policy = bc_policy
        self._config = config or RLConfig()
        self._on_progress = on_progress
        self._policies_dir = Path(policies_dir)

        # Verifier (create default if not provided)
        self._verifier = verifier or StepVerifier()

        # SAC agent
        sac_config = SACConfig(
            obs_dim=JOINT_COUNT,
            action_dim=JOINT_COUNT,
        )
        self._sac = SACAgent(sac_config)

        # Initialize from BC if available
        if bc_policy is not None:
            self._sac.init_from_bc(bc_policy)

        # Replay buffer
        self._buffer = ReplayBuffer(capacity=50_000)

        # Reward computer
        self._reward = StepRewardComputer(step, self._verifier)

        # Intervention detector
        self._detector = InterventionDetector(
            move_threshold=self._config.intervention_velocity_threshold,
            inference_hz=float(self._config.control_hz),
        )

        # Stop flag
        self._stop_requested = False

        # Stats
        self._total_interventions = 0
        self._success_history: list[bool] = []

    def request_stop(self) -> None:
        """Request graceful stop of training (checked each tick/episode)."""
        self._stop_requested = True

    async def train(self) -> RLResult:
        """Run the RL fine-tuning loop. Blocks until complete.

        Returns:
            RLResult with checkpoint path and training statistics.
        """
        # Pre-load demo data into buffer
        self._preload_demos()

        avg_critic = 0.0
        avg_actor = 0.0

        for episode in range(self._config.max_episodes):
            if self._stop_requested:
                logger.info("RL training stop requested at episode %d", episode)
                break

            # Run one episode
            ep_reward, ep_len, ep_interventions, ep_success = await self._run_episode()
            self._total_interventions += ep_interventions
            self._success_history.append(ep_success)

            # SAC updates
            if len(self._buffer) >= self._config.warmup_transitions:
                metrics = self._do_sac_updates(max(1, self._config.updates_per_step * ep_len))
                avg_critic = metrics.get("critic_loss", 0.0)
                avg_actor = metrics.get("actor_loss", 0.0)

            # Rolling success rate over last 10 episodes
            recent = self._success_history[-10:]
            success_rate = sum(recent) / len(recent)

            # Emit progress
            intervention_rate = ep_interventions / max(ep_len, 1)
            if self._on_progress:
                self._on_progress(
                    RLProgress(
                        episode=episode,
                        total_episodes=self._config.max_episodes,
                        episode_reward=ep_reward,
                        success=ep_success,
                        intervention_rate=intervention_rate,
                        critic_loss=avg_critic,
                        actor_loss=avg_actor,
                        buffer_size=len(self._buffer),
                    )
                )

            if episode % 10 == 0 or episode == self._config.max_episodes - 1:
                logger.info(
                    "Episode %d/%d: reward=%.2f, success_rate=%.2f, interventions=%d, buffer=%d",
                    episode,
                    self._config.max_episodes,
                    ep_reward,
                    success_rate,
                    ep_interventions,
                    len(self._buffer),
                )

            # Periodic checkpoint
            if episode > 0 and episode % self._config.save_interval_episodes == 0:
                self._save_checkpoint()

            # Early stop on success
            if (
                len(self._success_history) >= 10
                and success_rate >= self._config.success_rate_threshold
            ):
                logger.info(
                    "Success rate %.2f >= threshold %.2f, stopping",
                    success_rate,
                    self._config.success_rate_threshold,
                )
                break

        # Final save
        ckpt_path = self._save_checkpoint()
        self._save_buffer()

        recent = self._success_history[-10:] if self._success_history else []
        final_rate = sum(recent) / len(recent) if recent else 0.0

        return RLResult(
            checkpoint_path=ckpt_path,
            episodes_trained=len(self._success_history),
            final_success_rate=final_rate,
            total_interventions=self._total_interventions,
        )

    async def _run_episode(self) -> tuple[float, int, int, bool]:
        """Run a single RL episode.

        Returns:
            Tuple of (total_reward, episode_length, intervention_steps, success).
        """
        self._detector.reset()
        self._reward.reset()

        total_reward = 0.0
        interventions = 0
        force_history: list[float] = []

        # Get initial observation
        obs_list = obs_to_joints(self._robot.get_observation())
        obs_array = np.array(obs_list, dtype=np.float32)

        for _tick in range(self._config.max_steps_per_episode):
            if self._stop_requested:
                break

            # Check for human intervention
            is_intervening = self._detector.check(self._leader)

            if is_intervening:
                # Use leader action
                leader_obs = self._leader.get_action()
                action_list = obs_to_joints(leader_obs)
                action_array = np.array(action_list, dtype=np.float32)
                interventions += 1
            else:
                # Use SAC policy
                action_array = self._sac.select_action(obs_array)

            # Apply movement scale for safety
            current = np.array(obs_list, dtype=np.float32)
            delta = action_array - current
            safe_action = current + delta * self._config.movement_scale
            safe_list = safe_action.tolist()

            # Send to robot
            self._robot.send_action(joints_to_action(safe_list))

            # Read telemetry
            torques = read_torques_list(self._robot)
            peak_torque = max(abs(t) for t in torques) if torques else 0.0
            force_history.append(peak_torque)

            # Compute dense reward
            dense = self._reward.compute_timestep_reward(
                obs_array, safe_action, torques, force_history
            )
            total_reward += dense

            # Next observation
            next_obs_list = obs_to_joints(self._robot.get_observation())
            next_obs_array = np.array(next_obs_list, dtype=np.float32)

            # Store transition
            self._buffer.add(
                Transition(
                    obs=obs_array,
                    action=safe_action,
                    reward=dense,
                    next_obs=next_obs_array,
                    done=False,
                    is_intervention=is_intervening,
                )
            )

            obs_list = next_obs_list
            obs_array = next_obs_array

            await asyncio.sleep(1.0 / self._config.control_hz)

        # Terminal reward
        exec_data = ExecutionData(
            final_position=obs_list,
            force_history=force_history,
            peak_force=max(force_history) if force_history else 0.0,
            final_force=force_history[-1] if force_history else 0.0,
            duration_ms=len(force_history) * (1000.0 / self._config.control_hz),
        )
        terminal = await self._reward.compute_terminal_reward(exec_data)
        total_reward += terminal
        success = terminal > 0.0

        # Add terminal transition
        if len(obs_list) > 0:
            self._buffer.add(
                Transition(
                    obs=obs_array,
                    action=np.zeros_like(obs_array),
                    reward=terminal,
                    next_obs=obs_array,
                    done=True,
                    is_intervention=False,
                )
            )

        return total_reward, len(force_history), interventions, success

    def _do_sac_updates(self, num_updates: int) -> dict[str, float]:
        """Perform SAC gradient updates between episodes.

        Args:
            num_updates: Number of gradient steps.

        Returns:
            Average metrics dict.
        """
        total_metrics: dict[str, float] = {}

        batch_size = min(
            self._sac._config.batch_size,
            len(self._buffer),  # noqa: SLF001
        )
        if batch_size == 0:
            return {}

        for _ in range(num_updates):
            batch = self._buffer.sample_mixed(batch_size)
            metrics = self._sac.update(batch)
            for k, v in metrics.items():
                total_metrics[k] = total_metrics.get(k, 0.0) + v

        if num_updates > 0:
            for k in total_metrics:
                total_metrics[k] /= num_updates

        return total_metrics

    def _preload_demos(self) -> None:
        """Load HDF5 demos into the replay buffer as expert data."""
        demos_dir = Path("data/demos") / self._assembly_id / self._step.id
        if not demos_dir.exists():
            logger.debug("No demo directory found at %s", demos_dir)
            return

        demo_files = sorted(demos_dir.glob("*.hdf5"))
        if not demo_files:
            logger.debug("No HDF5 demos found in %s", demos_dir)
            return

        loaded = 0
        for demo_path in demo_files:
            try:
                with h5py.File(str(demo_path), "r") as f:
                    obs_data = f["observation/joint_positions"][:]
                    act_data = f["action/joint_positions"][:]
                    n_frames = min(len(obs_data), len(act_data))

                    for i in range(n_frames - 1):
                        self._buffer.add(
                            Transition(
                                obs=obs_data[i].astype(np.float32),
                                action=act_data[i].astype(np.float32),
                                reward=0.0,
                                next_obs=obs_data[i + 1].astype(np.float32),
                                done=False,
                                is_intervention=True,
                            )
                        )
                        loaded += 1
            except Exception as e:
                logger.warning("Failed to load demo %s: %s", demo_path, e)

        logger.info(
            "Pre-loaded %d transitions from %d demos into replay buffer",
            loaded,
            len(demo_files),
        )

    def _save_checkpoint(self) -> Path:
        """Save SAC agent checkpoint.

        Returns:
            Path to the saved checkpoint.
        """
        ckpt_dir = self._policies_dir / self._assembly_id / self._step.id
        ckpt_path = ckpt_dir / "policy_rl.pt"
        self._sac.save(ckpt_path)
        return ckpt_path

    def _save_buffer(self) -> None:
        """Save replay buffer to disk."""
        buf_dir = self._policies_dir / self._assembly_id / self._step.id
        buf_path = buf_dir / "replay_buffer.npz"
        self._buffer.save(buf_path)
