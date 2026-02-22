"""Training service — manages training jobs with persistence and presets.

Wraps ``PolicyTrainer`` with job lifecycle management: creation, progress
tracking, cancellation, and JSON persistence to survive page refreshes.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from nextis.errors import TrainingError
from nextis.learning.dataset import StepDataset
from nextis.learning.trainer import PolicyTrainer, TrainingConfig, TrainingProgress

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Training presets
# ------------------------------------------------------------------

PRESETS: dict[str, dict] = {
    "act": {
        "name": "ACT",
        "description": "Action Chunking Transformer — fast, reliable",
        "architecture": "act",
        "config": {"chunk_size": 10, "hidden_dim": 128, "learning_rate": 1e-4},
    },
    "act_large": {
        "name": "ACT Large",
        "description": "Larger ACT — better for complex motions",
        "architecture": "act",
        "config": {"chunk_size": 100, "hidden_dim": 256, "learning_rate": 1e-5},
    },
    "diffusion": {
        "name": "Diffusion Policy",
        "description": "DDPM denoising — handles multimodal action distributions",
        "architecture": "diffusion",
        "config": {"num_diffusion_steps": 100, "hidden_dim": 256, "learning_rate": 1e-4},
    },
    "pi0": {
        "name": "PI0.5 Flow",
        "description": "Flow matching — fast inference, smooth trajectories",
        "architecture": "pi0",
        "config": {"num_flow_steps": 20, "hidden_dim": 256, "learning_rate": 1e-4},
    },
}


# ------------------------------------------------------------------
# Training job
# ------------------------------------------------------------------


class TrainingJob:
    """In-memory training job with JSON persistence.

    Attributes:
        job_id: Unique job identifier.
        step_id: Assembly step being trained.
        assembly_id: Assembly the step belongs to.
        status: One of pending, running, completed, failed, cancelled.
        progress: Training progress 0.0–1.0.
        loss: Latest training loss.
        val_loss: Latest validation loss.
        checkpoint_path: Path to saved checkpoint on completion.
        error: Error message on failure.
        cancel_requested: Flag checked between epochs.
        created_at: Unix timestamp of job creation.
        architecture: Policy architecture used.
    """

    def __init__(
        self,
        job_id: str,
        step_id: str,
        assembly_id: str,
        architecture: str = "act",
    ) -> None:
        self.job_id = job_id
        self.step_id = step_id
        self.assembly_id = assembly_id
        self.architecture = architecture
        self.status = "pending"
        self.progress = 0.0
        self.loss: float | None = None
        self.val_loss: float | None = None
        self.checkpoint_path: str | None = None
        self.error: str | None = None
        self.cancel_requested = False
        self.created_at = time.time()

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "job_id": self.job_id,
            "step_id": self.step_id,
            "assembly_id": self.assembly_id,
            "architecture": self.architecture,
            "status": self.status,
            "progress": self.progress,
            "loss": self.loss,
            "val_loss": self.val_loss,
            "checkpoint_path": self.checkpoint_path,
            "error": self.error,
            "created_at": self.created_at,
        }

    def save(self, jobs_dir: Path) -> None:
        """Persist job state to ``{jobs_dir}/{job_id}.json``."""
        jobs_dir.mkdir(parents=True, exist_ok=True)
        path = jobs_dir / f"{self.job_id}.json"
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> TrainingJob:
        """Reconstruct a TrainingJob from a saved dict."""
        job = cls(
            job_id=data["job_id"],
            step_id=data["step_id"],
            assembly_id=data["assembly_id"],
            architecture=data.get("architecture", "act"),
        )
        job.status = data.get("status", "pending")
        job.progress = data.get("progress", 0.0)
        job.loss = data.get("loss")
        job.val_loss = data.get("val_loss")
        job.checkpoint_path = data.get("checkpoint_path")
        job.error = data.get("error")
        job.created_at = data.get("created_at", 0.0)
        return job


# ------------------------------------------------------------------
# Training service
# ------------------------------------------------------------------


class TrainingService:
    """Manages training jobs with progress tracking and persistence.

    Args:
        jobs_dir: Directory for persisting job state JSON files.
        demos_dir: Root demos directory for dataset building.
        policies_dir: Root policies directory for checkpoint saving.
    """

    def __init__(self, jobs_dir: Path, demos_dir: Path, policies_dir: Path) -> None:
        self._jobs_dir = jobs_dir
        self._demos_dir = demos_dir
        self._policies_dir = policies_dir
        self._jobs: dict[str, TrainingJob] = {}

    def start_training(
        self,
        step_id: str,
        assembly_id: str,
        architecture: str = "act",
        num_steps: int = 10_000,
    ) -> TrainingJob:
        """Create and register a new training job.

        Validates that demos exist before creating the job.

        Args:
            step_id: Step to train a policy for.
            assembly_id: Assembly the step belongs to.
            architecture: Policy architecture (act, diffusion, pi0).
            num_steps: Number of training steps (mapped to epochs).

        Returns:
            The created TrainingJob (status=pending). Caller must launch
            the async ``run_training`` coroutine separately.

        Raises:
            TrainingError: If no demos exist for the step.
        """
        demo_dir = self._demos_dir / assembly_id / step_id
        demo_files = list(demo_dir.glob("*.hdf5")) if demo_dir.exists() else []
        if not demo_files:
            raise TrainingError(
                f"No demos found for {assembly_id}/{step_id}. "
                "Record at least one demonstration first."
            )

        job_id = str(uuid.uuid4())[:8]
        job = TrainingJob(job_id, step_id, assembly_id, architecture)
        self._jobs[job_id] = job
        job.save(self._jobs_dir)

        logger.info(
            "Training job created: job=%s step=%s arch=%s demos=%d",
            job_id,
            step_id,
            architecture,
            len(demo_files),
        )
        return job

    async def run_training(self, job: TrainingJob) -> None:
        """Background coroutine: build dataset, train, save checkpoint.

        Updates the job object in-place with progress, loss, and status.
        Persists job state to disk on completion, failure, or cancellation.
        """
        try:
            job.status = "running"
            job.progress = 0.0
            job.save(self._jobs_dir)

            # Build dataset from HDF5 demos
            logger.info("Building dataset for %s/%s", job.assembly_id, job.step_id)
            dataset = StepDataset(job.assembly_id, job.step_id, str(self._demos_dir.parent))
            info = dataset.build()

            # Map num_steps to epochs
            num_epochs = max(10, 10_000 // 100)  # Default heuristic

            # Apply preset config if available
            preset = PRESETS.get(job.architecture, {})
            preset_cfg = preset.get("config", {})

            config = TrainingConfig(
                num_epochs=num_epochs,
                batch_size=32,
                learning_rate=preset_cfg.get("learning_rate", 1e-4),
                chunk_size=preset_cfg.get("chunk_size", 10),
                hidden_dim=preset_cfg.get("hidden_dim", 128),
                architecture=job.architecture,
                num_diffusion_steps=preset_cfg.get("num_diffusion_steps", 100),
                num_flow_steps=preset_cfg.get("num_flow_steps", 20),
            )

            def on_progress(p: TrainingProgress) -> None:
                job.progress = (p.epoch + 1) / p.total_epochs
                job.loss = p.loss
                job.val_loss = p.val_loss

            def should_cancel() -> bool:
                return job.cancel_requested

            # Train
            logger.info("Starting %s training: %d epochs", job.architecture, num_epochs)
            trainer = PolicyTrainer(str(self._policies_dir))
            result = await trainer.train(info, config, on_progress, should_cancel)

            job.status = "completed"
            job.progress = 1.0
            job.checkpoint_path = str(result.checkpoint_path)
            logger.info(
                "Training complete: %s (loss=%.6f)", result.checkpoint_path, result.final_loss
            )

        except TrainingError as e:
            if "cancelled" in str(e).lower():
                job.status = "cancelled"
                logger.info("Training job %s cancelled", job.job_id)
            else:
                job.status = "failed"
                job.error = str(e)
                logger.error("Training failed for %s: %s", job.job_id, e)

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            logger.error("Unexpected training error: %s", e, exc_info=True)

        finally:
            job.save(self._jobs_dir)

    def get_job(self, job_id: str) -> TrainingJob | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Request cancellation of a running job.

        Returns:
            True if the job was found and cancellation was requested.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status != "running":
            return False
        job.cancel_requested = True
        logger.info("Cancellation requested for job %s", job_id)
        return True

    def list_jobs(self) -> list[TrainingJob]:
        """List all jobs, sorted by creation time (newest first)."""
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def load_jobs_from_disk(self) -> None:
        """Load persisted jobs on startup.

        Jobs with status ``"running"`` are marked as ``"failed"`` since
        the server restarted while they were in progress.
        """
        if not self._jobs_dir.exists():
            return

        count = 0
        for fpath in self._jobs_dir.glob("*.json"):
            try:
                with open(fpath) as f:
                    data = json.load(f)
                job = TrainingJob.from_dict(data)

                # Stale running jobs become failed
                if job.status == "running":
                    job.status = "failed"
                    job.error = "Server restarted during training"
                    job.save(self._jobs_dir)

                self._jobs[job.job_id] = job
                count += 1
            except Exception as e:
                logger.warning("Failed to load job from %s: %s", fpath.name, e)

        if count:
            logger.info("Loaded %d training jobs from disk", count)
