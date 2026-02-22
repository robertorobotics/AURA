"""Circular replay buffer with intervention tagging for RLPD-style sampling.

Stores (obs, action, reward, next_obs, done, is_intervention) transitions
in a fixed-capacity circular buffer. Supports mixed sampling that guarantees
a minimum ratio of human intervention transitions per batch.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Transition:
    """Single environment transition.

    Attributes:
        obs: Observation vector.
        action: Action vector.
        reward: Scalar reward.
        next_obs: Next observation vector.
        done: Whether episode ended.
        is_intervention: True if this action came from the human leader.
    """

    obs: np.ndarray
    action: np.ndarray
    reward: float
    next_obs: np.ndarray
    done: bool
    is_intervention: bool


class ReplayBuffer:
    """Circular replay buffer with intervention tagging.

    Stores transitions in a plain list, overwriting the oldest entries
    when capacity is exceeded. Supports RLPD-style mixed sampling that
    guarantees a minimum fraction of human intervention data per batch.

    Args:
        capacity: Maximum number of transitions stored.
    """

    def __init__(self, capacity: int = 50_000) -> None:
        self._capacity = capacity
        self._buffer: list[Transition] = []
        self._pos: int = 0
        self._intervention_indices: list[int] = []
        self._autonomous_indices: list[int] = []

    def add(self, transition: Transition) -> None:
        """Add a single transition, overwriting oldest if at capacity."""
        if len(self._buffer) < self._capacity:
            idx = len(self._buffer)
            self._buffer.append(transition)
        else:
            idx = self._pos
            # Remove old index from tracking lists
            old = self._buffer[idx]
            if old.is_intervention:
                self._intervention_indices = [i for i in self._intervention_indices if i != idx]
            else:
                self._autonomous_indices = [i for i in self._autonomous_indices if i != idx]
            self._buffer[idx] = transition
            self._pos = (self._pos + 1) % self._capacity

        if transition.is_intervention:
            self._intervention_indices.append(idx)
        else:
            self._autonomous_indices.append(idx)

        if len(self._buffer) < self._capacity:
            self._pos = len(self._buffer)

    def sample(self, batch_size: int) -> list[Transition]:
        """Sample a uniformly random batch of transitions.

        Args:
            batch_size: Number of transitions to sample.

        Returns:
            List of sampled transitions.

        Raises:
            ValueError: If buffer has fewer transitions than batch_size.
        """
        if len(self._buffer) < batch_size:
            raise ValueError(f"Buffer has {len(self._buffer)} transitions, need {batch_size}")
        indices = random.sample(range(len(self._buffer)), batch_size)
        return [self._buffer[i] for i in indices]

    def sample_mixed(self, batch_size: int, intervention_ratio: float = 0.25) -> list[Transition]:
        """Sample a batch with a minimum fraction of intervention transitions.

        Ensures at least ``intervention_ratio`` of the batch comes from
        human interventions (the RLPD component). If insufficient intervention
        data exists, fills with whatever is available.

        Args:
            batch_size: Total number of transitions to sample.
            intervention_ratio: Minimum fraction of intervention transitions.

        Returns:
            List of sampled transitions.

        Raises:
            ValueError: If buffer has fewer transitions than batch_size.
        """
        if len(self._buffer) < batch_size:
            raise ValueError(f"Buffer has {len(self._buffer)} transitions, need {batch_size}")

        n_intervention = int(batch_size * intervention_ratio)

        # Clamp to available counts
        avail_intervention = len(self._intervention_indices)
        avail_autonomous = len(self._autonomous_indices)

        actual_intervention = min(n_intervention, avail_intervention)
        actual_autonomous = batch_size - actual_intervention

        # If not enough autonomous, pull more from intervention
        if actual_autonomous > avail_autonomous:
            actual_autonomous = avail_autonomous
            actual_intervention = min(batch_size - actual_autonomous, avail_intervention)

        indices: list[int] = []
        if actual_intervention > 0:
            indices.extend(random.sample(self._intervention_indices, actual_intervention))
        if actual_autonomous > 0:
            indices.extend(random.sample(self._autonomous_indices, actual_autonomous))

        # Fill remainder if both pools are small
        remaining = batch_size - len(indices)
        if remaining > 0:
            all_indices = list(range(len(self._buffer)))
            extras = random.sample(all_indices, min(remaining, len(all_indices)))
            indices.extend(extras[:remaining])

        return [self._buffer[i] for i in indices]

    def __len__(self) -> int:
        return len(self._buffer)

    @property
    def intervention_count(self) -> int:
        """Number of intervention transitions currently stored."""
        return len(self._intervention_indices)

    def save(self, path: Path) -> None:
        """Save buffer contents to disk via np.savez.

        Args:
            path: File path (should end in .npz).
        """
        n = len(self._buffer)
        if n == 0:
            logger.warning("Saving empty replay buffer to %s", path)

        obs_dim = self._buffer[0].obs.shape[0] if n > 0 else 0
        act_dim = self._buffer[0].action.shape[0] if n > 0 else 0

        obs_arr = np.zeros((n, obs_dim), dtype=np.float32)
        act_arr = np.zeros((n, act_dim), dtype=np.float32)
        rew_arr = np.zeros(n, dtype=np.float32)
        next_obs_arr = np.zeros((n, obs_dim), dtype=np.float32)
        done_arr = np.zeros(n, dtype=bool)
        intervention_arr = np.zeros(n, dtype=bool)

        for i, t in enumerate(self._buffer):
            obs_arr[i] = t.obs
            act_arr[i] = t.action
            rew_arr[i] = t.reward
            next_obs_arr[i] = t.next_obs
            done_arr[i] = t.done
            intervention_arr[i] = t.is_intervention

        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            str(path),
            obs=obs_arr,
            action=act_arr,
            reward=rew_arr,
            next_obs=next_obs_arr,
            done=done_arr,
            is_intervention=intervention_arr,
            metadata=np.array([self._capacity, self._pos]),
        )
        logger.info("Saved replay buffer (%d transitions) to %s", n, path)

    @classmethod
    def load(cls, path: Path) -> ReplayBuffer:
        """Load a previously saved buffer from disk.

        Args:
            path: Path to the .npz file.

        Returns:
            Reconstructed ReplayBuffer with all transitions.
        """
        data = np.load(str(path))
        capacity = int(data["metadata"][0])
        buf = cls(capacity=capacity)

        n = len(data["obs"])
        for i in range(n):
            t = Transition(
                obs=data["obs"][i].copy(),
                action=data["action"][i].copy(),
                reward=float(data["reward"][i]),
                next_obs=data["next_obs"][i].copy(),
                done=bool(data["done"][i]),
                is_intervention=bool(data["is_intervention"][i]),
            )
            buf.add(t)

        logger.info("Loaded replay buffer (%d transitions) from %s", n, path)
        return buf
