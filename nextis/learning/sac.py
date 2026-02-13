"""Minimal Soft Actor-Critic (SAC) for joint-space RL fine-tuning.

Pure PyTorch implementation with no external RL library dependencies.
Operates on low-dimensional joint-space observations and actions (no images).
Supports warm-starting the actor from a BC-pretrained MinimalACT checkpoint.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from nextis.learning.replay_buffer import Transition

logger = logging.getLogger(__name__)

LOG_STD_MIN = -20.0
LOG_STD_MAX = 2.0


@dataclass
class SACConfig:
    """SAC hyperparameters.

    Attributes:
        obs_dim: Observation vector size.
        action_dim: Action vector size.
        actor_lr: Actor network learning rate.
        critic_lr: Critic network learning rate.
        temperature_lr: Temperature (alpha) learning rate.
        discount: Reward discount factor.
        tau: Target network soft update rate.
        batch_size: Mini-batch size for updates.
        device: PyTorch device string.
    """

    obs_dim: int = 7
    action_dim: int = 7
    actor_lr: float = 3e-4
    critic_lr: float = 3e-4
    temperature_lr: float = 3e-4
    discount: float = 0.99
    tau: float = 0.005
    batch_size: int = 64
    device: str = "cpu"


class GaussianActor(nn.Module):
    """Squashed Gaussian policy network.

    Outputs a tanh-squashed action sampled from a diagonal Gaussian.
    Architecture: obs_dim -> 256 -> 256 -> mean + log_std.

    Args:
        obs_dim: Observation dimension.
        action_dim: Action dimension.
        hidden_dim: Hidden layer size.
    """

    def __init__(self, obs_dim: int, action_dim: int, hidden_dim: int = 256) -> None:
        super().__init__()
        self.fc1 = nn.Linear(obs_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.mean_head = nn.Linear(hidden_dim, action_dim)
        self.log_std_head = nn.Linear(hidden_dim, action_dim)

    def forward(
        self, obs: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Compute action and log probability via reparameterization.

        Args:
            obs: Observation tensor of shape (B, obs_dim).

        Returns:
            Tuple of (action, log_prob), both shape (B, action_dim) and (B, 1).
        """
        h = F.relu(self.fc1(obs))
        h = F.relu(self.fc2(h))

        mean = self.mean_head(h)
        log_std = self.log_std_head(h).clamp(LOG_STD_MIN, LOG_STD_MAX)
        std = log_std.exp()

        # Reparameterized sample
        normal = torch.distributions.Normal(mean, std)
        x_t = normal.rsample()
        action = torch.tanh(x_t)

        # Log probability with tanh correction
        log_prob = normal.log_prob(x_t)
        log_prob -= torch.log(1.0 - action.pow(2) + 1e-6)
        log_prob = log_prob.sum(dim=-1, keepdim=True)

        return action, log_prob

    def mean_action(self, obs: torch.Tensor) -> torch.Tensor:
        """Deterministic action (no sampling) for evaluation.

        Args:
            obs: Observation tensor of shape (B, obs_dim).

        Returns:
            Deterministic action of shape (B, action_dim).
        """
        h = F.relu(self.fc1(obs))
        h = F.relu(self.fc2(h))
        return torch.tanh(self.mean_head(h))


class QNetwork(nn.Module):
    """Single Q-network for SAC critic.

    Architecture: (obs_dim + action_dim) -> 256 -> 256 -> 1.

    Args:
        obs_dim: Observation dimension.
        action_dim: Action dimension.
        hidden_dim: Hidden layer size.
    """

    def __init__(self, obs_dim: int, action_dim: int, hidden_dim: int = 256) -> None:
        super().__init__()
        self.fc1 = nn.Linear(obs_dim + action_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.fc3 = nn.Linear(hidden_dim, 1)

    def forward(self, obs: torch.Tensor, action: torch.Tensor) -> torch.Tensor:
        """Compute Q-value for (obs, action) pair.

        Args:
            obs: Observation tensor (B, obs_dim).
            action: Action tensor (B, action_dim).

        Returns:
            Q-value tensor (B, 1).
        """
        x = torch.cat([obs, action], dim=-1)
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        return self.fc3(x)


class SACAgent:
    """Soft Actor-Critic agent with auto-tuned temperature.

    Manages actor, twin critics, target critics, and learnable log_alpha.
    Implements the standard SAC update loop.

    Args:
        config: SAC hyperparameters.
    """

    def __init__(self, config: SACConfig) -> None:
        self._config = config
        self._device = torch.device(config.device)

        # Actor
        self._actor = GaussianActor(
            config.obs_dim, config.action_dim
        ).to(self._device)

        # Twin critics
        self._q1 = QNetwork(config.obs_dim, config.action_dim).to(self._device)
        self._q2 = QNetwork(config.obs_dim, config.action_dim).to(self._device)

        # Target critics (EMA copies)
        self._q1_target = copy.deepcopy(self._q1)
        self._q2_target = copy.deepcopy(self._q2)
        for p in self._q1_target.parameters():
            p.requires_grad = False
        for p in self._q2_target.parameters():
            p.requires_grad = False

        # Learnable temperature
        self._log_alpha = torch.zeros(1, requires_grad=True, device=self._device)
        self._target_entropy = -float(config.action_dim)

        # Optimizers
        self._actor_opt = torch.optim.Adam(
            self._actor.parameters(), lr=config.actor_lr
        )
        self._critic_opt = torch.optim.Adam(
            list(self._q1.parameters()) + list(self._q2.parameters()),
            lr=config.critic_lr,
        )
        self._alpha_opt = torch.optim.Adam(
            [self._log_alpha], lr=config.temperature_lr
        )

    @property
    def alpha(self) -> float:
        """Current temperature value."""
        return self._log_alpha.exp().item()

    def select_action(
        self, obs: np.ndarray, deterministic: bool = False
    ) -> np.ndarray:
        """Select an action from the policy.

        Args:
            obs: Observation vector of shape (obs_dim,).
            deterministic: If True, return the mean action (no sampling).

        Returns:
            Action vector of shape (action_dim,).
        """
        obs_t = torch.tensor(obs, dtype=torch.float32, device=self._device).unsqueeze(0)

        with torch.no_grad():
            if deterministic:
                action = self._actor.mean_action(obs_t)
            else:
                action, _ = self._actor(obs_t)

        return action.squeeze(0).cpu().numpy()

    def update(self, transitions: list[Transition]) -> dict[str, float]:
        """Run one SAC update step on a batch of transitions.

        Args:
            transitions: List of transitions to train on.

        Returns:
            Dict with keys: critic_loss, actor_loss, alpha_loss, alpha.
        """
        batch = self._transitions_to_tensors(transitions)
        obs = batch["obs"]
        action = batch["action"]
        reward = batch["reward"]
        next_obs = batch["next_obs"]
        done = batch["done"]

        # --- Critic update ---
        with torch.no_grad():
            next_action, next_log_prob = self._actor(next_obs)
            q1_next = self._q1_target(next_obs, next_action)
            q2_next = self._q2_target(next_obs, next_action)
            q_next = torch.min(q1_next, q2_next) - self._log_alpha.exp() * next_log_prob
            target_q = reward + self._config.discount * (1.0 - done) * q_next

        q1_pred = self._q1(obs, action)
        q2_pred = self._q2(obs, action)
        critic_loss = F.mse_loss(q1_pred, target_q) + F.mse_loss(q2_pred, target_q)

        self._critic_opt.zero_grad()
        critic_loss.backward()
        self._critic_opt.step()

        # --- Actor update ---
        new_action, log_prob = self._actor(obs)
        q1_new = self._q1(obs, new_action)
        q2_new = self._q2(obs, new_action)
        q_new = torch.min(q1_new, q2_new)
        actor_loss = (self._log_alpha.exp().detach() * log_prob - q_new).mean()

        self._actor_opt.zero_grad()
        actor_loss.backward()
        self._actor_opt.step()

        # --- Alpha update ---
        alpha_loss = -(
            self._log_alpha.exp() * (log_prob.detach() + self._target_entropy)
        ).mean()

        self._alpha_opt.zero_grad()
        alpha_loss.backward()
        self._alpha_opt.step()

        # --- Soft-update target networks ---
        self._soft_update(self._q1, self._q1_target)
        self._soft_update(self._q2, self._q2_target)

        return {
            "critic_loss": critic_loss.item(),
            "actor_loss": actor_loss.item(),
            "alpha_loss": alpha_loss.item(),
            "alpha": self.alpha,
        }

    def init_from_bc(self, bc_policy: object) -> None:
        """Initialize the actor's first layer from a BC policy's obs_proj.

        Copies weights from ``MinimalACT.obs_proj`` to the actor's ``fc1``.
        Only copies the overlapping dimensions if hidden sizes differ.

        Args:
            bc_policy: A Policy object whose ``_model`` has an ``obs_proj`` layer.
        """
        try:
            bc_model = bc_policy._model  # noqa: SLF001
            if not hasattr(bc_model, "obs_proj"):
                logger.warning("BC model has no obs_proj layer, skipping init")
                return

            src_weight = bc_model.obs_proj.weight.data  # (bc_hidden, obs_dim)
            src_bias = bc_model.obs_proj.bias.data  # (bc_hidden,)
            dst_weight = self._actor.fc1.weight.data  # (256, obs_dim)
            dst_bias = self._actor.fc1.bias.data  # (256,)

            rows = min(src_weight.shape[0], dst_weight.shape[0])
            cols = min(src_weight.shape[1], dst_weight.shape[1])

            dst_weight[:rows, :cols] = src_weight[:rows, :cols].clone()
            dst_bias[:rows] = src_bias[:rows].clone()

            logger.info(
                "Initialized actor fc1 from BC obs_proj (%d/%d rows copied)",
                rows,
                dst_weight.shape[0],
            )
        except Exception as e:
            logger.warning("Failed to init from BC: %s", e)

    def save(self, path: Path) -> None:
        """Save agent state to disk.

        Args:
            path: Output file path (typically policy_rl.pt).
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "actor_state_dict": self._actor.state_dict(),
                "q1_state_dict": self._q1.state_dict(),
                "q2_state_dict": self._q2.state_dict(),
                "q1_target_state_dict": self._q1_target.state_dict(),
                "q2_target_state_dict": self._q2_target.state_dict(),
                "log_alpha": self._log_alpha.detach().cpu(),
                "config": {
                    "obs_dim": self._config.obs_dim,
                    "action_dim": self._config.action_dim,
                    "actor_lr": self._config.actor_lr,
                    "critic_lr": self._config.critic_lr,
                    "temperature_lr": self._config.temperature_lr,
                    "discount": self._config.discount,
                    "tau": self._config.tau,
                    "batch_size": self._config.batch_size,
                    "device": self._config.device,
                },
            },
            str(path),
        )
        logger.info("Saved SAC agent to %s", path)

    @classmethod
    def load(cls, path: Path) -> SACAgent:
        """Load a saved SAC agent from disk.

        Args:
            path: Path to the checkpoint file.

        Returns:
            Restored SACAgent.
        """
        ckpt = torch.load(str(path), map_location="cpu", weights_only=False)
        cfg_dict = ckpt["config"]
        config = SACConfig(**cfg_dict)
        agent = cls(config)

        agent._actor.load_state_dict(ckpt["actor_state_dict"])
        agent._q1.load_state_dict(ckpt["q1_state_dict"])
        agent._q2.load_state_dict(ckpt["q2_state_dict"])
        agent._q1_target.load_state_dict(ckpt["q1_target_state_dict"])
        agent._q2_target.load_state_dict(ckpt["q2_target_state_dict"])
        agent._log_alpha.data.copy_(ckpt["log_alpha"])

        logger.info("Loaded SAC agent from %s", path)
        return agent

    def _transitions_to_tensors(
        self, transitions: list[Transition]
    ) -> dict[str, torch.Tensor]:
        """Convert a list of transitions to batched tensors."""
        obs = np.stack([t.obs for t in transitions])
        actions = np.stack([t.action for t in transitions])
        rewards = np.array([t.reward for t in transitions], dtype=np.float32)
        next_obs = np.stack([t.next_obs for t in transitions])
        dones = np.array([t.done for t in transitions], dtype=np.float32)

        return {
            "obs": torch.tensor(obs, dtype=torch.float32, device=self._device),
            "action": torch.tensor(actions, dtype=torch.float32, device=self._device),
            "reward": torch.tensor(
                rewards, dtype=torch.float32, device=self._device
            ).unsqueeze(-1),
            "next_obs": torch.tensor(
                next_obs, dtype=torch.float32, device=self._device
            ),
            "done": torch.tensor(
                dones, dtype=torch.float32, device=self._device
            ).unsqueeze(-1),
        }

    def _soft_update(self, source: nn.Module, target: nn.Module) -> None:
        """Polyak-average update of target network."""
        tau = self._config.tau
        for sp, tp in zip(source.parameters(), target.parameters(), strict=False):
            tp.data.mul_(1.0 - tau).add_(sp.data, alpha=tau)
