"""Unified configuration loader and path constants.

Single source of truth for all filesystem paths and YAML config I/O.
Falls back through a chain of config locations for fresh installs and tests.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# --- Path constants (derived from project root) ---

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Config paths
CONFIGS_DIR = PROJECT_ROOT / "configs"
CONFIG_PATH = CONFIGS_DIR / "settings.yaml"
CONFIG_EXAMPLE_PATH = CONFIGS_DIR / "settings.example.yaml"
LEGACY_CONFIG_PATH = CONFIGS_DIR / "arms" / "settings.yaml"
ASSEMBLIES_DIR = CONFIGS_DIR / "assemblies"
OVERRIDES_DIR = CONFIGS_DIR / "overrides"
CALIBRATION_DIR = CONFIGS_DIR / "calibration"

# Data paths (all gitignored, created on first use)
DATA_DIR = PROJECT_ROOT / "data"
MESHES_DIR = DATA_DIR / "meshes"
DEMOS_DIR = DATA_DIR / "demos"
POLICIES_DIR = DATA_DIR / "policies"
DATASETS_DIR = DATA_DIR / "datasets"
TRAINING_JOBS_DIR = DATA_DIR / "training_jobs"
ANALYTICS_DIR = DATA_DIR / "analytics"

_config_lock = threading.Lock()


def _resolve_config_path() -> Path | None:
    """Find the first existing config file in the fallback chain.

    Order: settings.yaml → legacy arms/settings.yaml → settings.example.yaml.
    Returns None if no config file exists.
    """
    for path in (CONFIG_PATH, LEGACY_CONFIG_PATH, CONFIG_EXAMPLE_PATH):
        if path.exists():
            return path
    return None


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load the YAML config, falling back through the config chain.

    Args:
        path: Explicit path to load. If None, uses the fallback chain.

    Returns:
        Parsed config dict, or empty dict if no config file found.
    """
    if path is None:
        path = _resolve_config_path()
    if path is None:
        logger.warning("No config file found in fallback chain")
        return {}

    with _config_lock, open(path) as f:
        data = yaml.safe_load(f) or {}

    logger.info("Loaded config from %s", path)
    return data


def save_config(data: dict[str, Any], path: Path | None = None) -> None:
    """Write config data to YAML.

    Args:
        data: Config dict to persist.
        path: Target file. Defaults to CONFIG_PATH (configs/settings.yaml).
    """
    if path is None:
        path = CONFIG_PATH
    with _config_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    logger.info("Saved config to %s", path)
