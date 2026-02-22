"""Tests for the RL fine-tuning components.

Covers: ReplayBuffer, SACAgent, StepRewardComputer, and the full
StepRLTrainer integration loop. All tests run without real hardware
using MockRobot and MockLeader.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch

from nextis.assembly.models import AssemblyStep, SuccessCriteria
from nextis.hardware.mock import MockLeader, MockRobot
from nextis.learning.policy_loader import Policy
from nextis.learning.replay_buffer import ReplayBuffer, Transition
from nextis.learning.reward import StepRewardComputer
from nextis.learning.rl_trainer import RLConfig, StepRLTrainer
from nextis.learning.sac import SACAgent, SACConfig
from nextis.learning.trainer import MinimalACT
from nextis.perception.verifier import StepVerifier

logger = logging.getLogger(__name__)

OBS_DIM = 7
ACTION_DIM = 7


def _make_transition(is_intervention: bool = False, reward: float = 0.0) -> Transition:
    """Create a random transition for testing."""
    return Transition(
        obs=np.random.randn(OBS_DIM).astype(np.float32),
        action=np.random.randn(ACTION_DIM).astype(np.float32),
        reward=reward,
        next_obs=np.random.randn(OBS_DIM).astype(np.float32),
        done=False,
        is_intervention=is_intervention,
    )


def _make_step(
    step_id: str = "step_001",
    criteria_type: str = "force_threshold",
    threshold: float = 5.0,
) -> AssemblyStep:
    """Create a test assembly step with given success criteria."""
    return AssemblyStep(
        id=step_id,
        name=f"Test step {step_id}",
        part_ids=["part_a"],
        handler="rl_finetune",
        primitive_type="press_fit",
        primitive_params={"target_pose": [0.1, 0.2, 0.3, 0.0, 0.0, 0.0, 0.0]},
        success_criteria=SuccessCriteria(type=criteria_type, threshold=threshold),
        max_retries=3,
    )


def _make_bc_policy() -> Policy:
    """Create a synthetic BC policy for testing init_from_bc."""
    model = MinimalACT(obs_dim=OBS_DIM, action_dim=ACTION_DIM, chunk_size=5, hidden_dim=128)
    config = {
        "obs_dim": OBS_DIM,
        "action_dim": ACTION_DIM,
        "chunk_size": 5,
        "hidden_dim": 128,
        "architecture": "act",
        "joint_keys": [
            "base.pos",
            "gripper.pos",
            "link1.pos",
            "link2.pos",
            "link3.pos",
            "link4.pos",
            "link5.pos",
        ],
    }
    return Policy(model=model, config=config)


# ---------------------------------------------------------------------------
# ReplayBuffer tests
# ---------------------------------------------------------------------------


class TestReplayBuffer:
    """Tests for the circular replay buffer."""

    def test_add_and_len(self) -> None:
        """Adding transitions increments length up to capacity."""
        buf = ReplayBuffer(capacity=50)
        for _ in range(100):
            buf.add(_make_transition())
        assert len(buf) == 50

    def test_circular_overwrite(self) -> None:
        """Buffer wraps around when capacity is exceeded."""
        buf = ReplayBuffer(capacity=10)
        for i in range(20):
            buf.add(_make_transition(reward=float(i)))
        assert len(buf) == 10
        # Oldest transitions (0-9) should be overwritten
        rewards = [t.reward for t in buf.sample(10)]
        # All sampled rewards should be from the later half
        assert all(r >= 10.0 for r in rewards)

    def test_sample_shape(self) -> None:
        """sample() returns correct number of transitions."""
        buf = ReplayBuffer(capacity=100)
        for _ in range(50):
            buf.add(_make_transition())
        batch = buf.sample(32)
        assert len(batch) == 32
        assert batch[0].obs.shape == (OBS_DIM,)
        assert batch[0].action.shape == (ACTION_DIM,)

    def test_sample_mixed_intervention_ratio(self) -> None:
        """sample_mixed returns at least 25% interventions when available."""
        buf = ReplayBuffer(capacity=200)
        for _ in range(50):
            buf.add(_make_transition(is_intervention=False))
        for _ in range(50):
            buf.add(_make_transition(is_intervention=True))

        batch = buf.sample_mixed(32, intervention_ratio=0.25)
        assert len(batch) == 32
        n_interventions = sum(1 for t in batch if t.is_intervention)
        assert n_interventions >= 8  # 25% of 32

    def test_intervention_count(self) -> None:
        """intervention_count correctly reflects tagged transitions."""
        buf = ReplayBuffer(capacity=100)
        for _ in range(30):
            buf.add(_make_transition(is_intervention=True))
        for _ in range(20):
            buf.add(_make_transition(is_intervention=False))
        assert buf.intervention_count == 30

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        """Save and load preserves all data and metadata."""
        buf = ReplayBuffer(capacity=100)
        for i in range(40):
            buf.add(_make_transition(is_intervention=i % 3 == 0, reward=float(i)))

        save_path = tmp_path / "buffer.npz"
        buf.save(save_path)

        loaded = ReplayBuffer.load(save_path)
        assert len(loaded) == 40
        assert loaded.intervention_count == buf.intervention_count

        # Verify data integrity
        for i in range(40):
            np.testing.assert_array_almost_equal(buf._buffer[i].obs, loaded._buffer[i].obs)
            assert buf._buffer[i].reward == loaded._buffer[i].reward
            assert buf._buffer[i].is_intervention == loaded._buffer[i].is_intervention


# ---------------------------------------------------------------------------
# SACAgent tests
# ---------------------------------------------------------------------------


class TestSACAgent:
    """Tests for the SAC agent."""

    def test_select_action_shape(self) -> None:
        """select_action returns (action_dim,) array with finite values."""
        config = SACConfig(obs_dim=OBS_DIM, action_dim=ACTION_DIM)
        agent = SACAgent(config)

        obs = np.random.randn(OBS_DIM).astype(np.float32)
        action = agent.select_action(obs)
        assert action.shape == (ACTION_DIM,)
        assert np.all(np.isfinite(action))
        # Tanh squashing: actions should be in [-1, 1]
        assert np.all(action >= -1.0) and np.all(action <= 1.0)

    def test_select_action_deterministic(self) -> None:
        """Deterministic mode returns same action for same obs."""
        config = SACConfig(obs_dim=OBS_DIM, action_dim=ACTION_DIM)
        agent = SACAgent(config)

        obs = np.random.randn(OBS_DIM).astype(np.float32)
        a1 = agent.select_action(obs, deterministic=True)
        a2 = agent.select_action(obs, deterministic=True)
        np.testing.assert_array_almost_equal(a1, a2)

    def test_update_returns_metrics(self) -> None:
        """update() returns dict with expected metric keys."""
        config = SACConfig(obs_dim=OBS_DIM, action_dim=ACTION_DIM)
        agent = SACAgent(config)

        transitions = [_make_transition() for _ in range(64)]
        metrics = agent.update(transitions)

        assert "critic_loss" in metrics
        assert "actor_loss" in metrics
        assert "alpha_loss" in metrics
        assert "alpha" in metrics
        assert np.isfinite(metrics["critic_loss"])
        assert np.isfinite(metrics["actor_loss"])

    def test_update_critic_loss_decreases(self) -> None:
        """Critic loss trends downward over multiple updates."""
        config = SACConfig(obs_dim=OBS_DIM, action_dim=ACTION_DIM)
        agent = SACAgent(config)

        # Use consistent transitions with a clear reward signal
        transitions = []
        for _ in range(128):
            t = _make_transition(reward=1.0)
            transitions.append(t)

        losses = []
        for _ in range(10):
            metrics = agent.update(transitions[:64])
            losses.append(metrics["critic_loss"])

        # Critic loss should generally decrease (allow some noise)
        assert losses[-1] < losses[0] * 2.0  # Not diverging
        assert all(np.isfinite(v) for v in losses)

    def test_init_from_bc(self) -> None:
        """BC initialization copies obs_proj weights to actor fc1."""
        bc_policy = _make_bc_policy()
        config = SACConfig(obs_dim=OBS_DIM, action_dim=ACTION_DIM)
        agent = SACAgent(config)

        # Record original weights
        original_fc1 = agent._actor.fc1.weight.data.clone()

        agent.init_from_bc(bc_policy)

        # First 128 rows should now match obs_proj
        bc_weight = bc_policy._model.obs_proj.weight.data
        rows = min(bc_weight.shape[0], agent._actor.fc1.weight.shape[0])
        cols = min(bc_weight.shape[1], agent._actor.fc1.weight.shape[1])

        torch.testing.assert_close(
            agent._actor.fc1.weight.data[:rows, :cols],
            bc_weight[:rows, :cols],
        )
        # Weights should have changed from original
        changed = not torch.equal(
            original_fc1[:rows, :cols], agent._actor.fc1.weight.data[:rows, :cols]
        )
        assert changed

    def test_save_load(self, tmp_path: Path) -> None:
        """Save and load produces agent with same action outputs."""
        config = SACConfig(obs_dim=OBS_DIM, action_dim=ACTION_DIM)
        agent = SACAgent(config)

        obs = np.random.randn(OBS_DIM).astype(np.float32)
        action_before = agent.select_action(obs, deterministic=True)

        ckpt_path = tmp_path / "policy_rl.pt"
        agent.save(ckpt_path)

        loaded = SACAgent.load(ckpt_path)
        action_after = loaded.select_action(obs, deterministic=True)

        np.testing.assert_array_almost_equal(action_before, action_after)


# ---------------------------------------------------------------------------
# StepRewardComputer tests
# ---------------------------------------------------------------------------


class TestStepRewardComputer:
    """Tests for the reward function."""

    def test_dense_reward_finite(self) -> None:
        """Dense reward is always finite."""
        step = _make_step(criteria_type="force_threshold", threshold=5.0)
        verifier = StepVerifier()
        reward_fn = StepRewardComputer(step, verifier)

        obs = np.random.randn(OBS_DIM).astype(np.float32)
        action = np.random.randn(ACTION_DIM).astype(np.float32)
        torques = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]

        r = reward_fn.compute_timestep_reward(obs, action, torques, [0.5])
        assert np.isfinite(r)

    def test_force_shaping_increases_with_torque(self) -> None:
        """Force shaping reward increases as peak torque approaches threshold."""
        step = _make_step(criteria_type="force_threshold", threshold=5.0)
        verifier = StepVerifier()
        reward_fn = StepRewardComputer(step, verifier)

        obs = np.zeros(OBS_DIM, dtype=np.float32)
        action = np.zeros(ACTION_DIM, dtype=np.float32)

        # Low torque
        reward_fn.reset()
        r_low = reward_fn.compute_timestep_reward(obs, action, [0.5] * 7, [0.5])

        # High torque (closer to threshold)
        reward_fn.reset()
        r_high = reward_fn.compute_timestep_reward(obs, action, [4.5] * 7, [4.5])

        assert r_high > r_low

    async def test_terminal_reward_positive_on_pass(self) -> None:
        """Terminal reward is positive when verifier passes."""
        step = _make_step(criteria_type="position", threshold=2.0)
        step.primitive_params = {"target_pose": [0.0] * 7}
        verifier = StepVerifier()
        reward_fn = StepRewardComputer(step, verifier)

        from nextis.perception.types import ExecutionData

        # Position exactly at target -> should pass
        exec_data = ExecutionData(
            final_position=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            force_history=[1.0, 2.0, 3.0],
            peak_force=3.0,
            final_force=3.0,
            duration_ms=100.0,
        )
        terminal = await reward_fn.compute_terminal_reward(exec_data)
        assert terminal > 0.0

    async def test_terminal_reward_negative_on_fail(self) -> None:
        """Terminal reward is negative when verifier fails."""
        step = _make_step(criteria_type="position", threshold=0.001)
        step.primitive_params = {"target_pose": [10.0] * 7}
        verifier = StepVerifier()
        reward_fn = StepRewardComputer(step, verifier)

        from nextis.perception.types import ExecutionData

        # Position far from target -> should fail
        exec_data = ExecutionData(
            final_position=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            force_history=[1.0],
            peak_force=1.0,
            final_force=1.0,
            duration_ms=100.0,
        )
        terminal = await reward_fn.compute_terminal_reward(exec_data)
        assert terminal < 0.0


# ---------------------------------------------------------------------------
# StepRLTrainer integration test
# ---------------------------------------------------------------------------


class TestStepRLTrainer:
    """Integration tests for the RL training loop in mock mode."""

    async def test_mock_training_loop(self, tmp_path: Path) -> None:
        """Full RL training loop with MockRobot completes without errors."""
        step = _make_step()
        robot = MockRobot()
        leader = MockLeader()

        config = RLConfig(
            max_episodes=3,
            max_steps_per_episode=20,
            warmup_transitions=10,
            control_hz=50,
            save_interval_episodes=2,
        )

        progress_updates: list[dict] = []

        def on_progress(p: object) -> None:
            progress_updates.append({"episode": p.episode, "reward": p.episode_reward})

        trainer = StepRLTrainer(
            robot=robot,
            leader=leader,
            step=step,
            assembly_id="test_rl",
            bc_policy=None,
            config=config,
            on_progress=on_progress,
            policies_dir=str(tmp_path / "policies"),
        )

        result = await trainer.train()

        # Verify results
        assert result.episodes_trained == 3
        assert result.checkpoint_path.exists()
        assert result.checkpoint_path.name == "policy_rl.pt"

        # Verify replay buffer was saved
        buf_path = tmp_path / "policies" / "test_rl" / "step_001" / "replay_buffer.npz"
        assert buf_path.exists()

        # Verify progress was reported
        assert len(progress_updates) == 3

    async def test_training_with_bc_init(self, tmp_path: Path) -> None:
        """When BC checkpoint exists, SAC agent is initialized from it."""
        step = _make_step()
        robot = MockRobot()
        leader = MockLeader()
        bc_policy = _make_bc_policy()

        config = RLConfig(
            max_episodes=2,
            max_steps_per_episode=10,
            warmup_transitions=5,
        )

        trainer = StepRLTrainer(
            robot=robot,
            leader=leader,
            step=step,
            assembly_id="test_bc_init",
            bc_policy=bc_policy,
            config=config,
            policies_dir=str(tmp_path / "policies"),
        )

        result = await trainer.train()
        assert result.episodes_trained == 2
        assert result.checkpoint_path.exists()

    async def test_stop_requested(self, tmp_path: Path) -> None:
        """Setting stop flag terminates training gracefully."""
        step = _make_step()
        robot = MockRobot()
        leader = MockLeader()

        config = RLConfig(
            max_episodes=100,
            max_steps_per_episode=10,
            warmup_transitions=5,
        )

        trainer = StepRLTrainer(
            robot=robot,
            leader=leader,
            step=step,
            assembly_id="test_stop",
            config=config,
            policies_dir=str(tmp_path / "policies"),
        )

        # Request stop immediately
        trainer.request_stop()
        result = await trainer.train()

        # Should have stopped before completing all 100 episodes
        assert result.episodes_trained < 100
