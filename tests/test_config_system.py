"""Tests for the unified config loader and SystemState lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient  # noqa: TC002

# ------------------------------------------------------------------
# Config loader tests
# ------------------------------------------------------------------


def test_load_config_from_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """load_config reads settings.yaml when it exists."""
    import nextis.config as config_mod

    cfg_file = tmp_path / "settings.yaml"
    cfg_file.write_text(yaml.dump({"arms": {"a1": {"name": "Arm1"}}}))

    monkeypatch.setattr(config_mod, "CONFIG_PATH", cfg_file)
    monkeypatch.setattr(config_mod, "LEGACY_CONFIG_PATH", tmp_path / "nope.yaml")
    monkeypatch.setattr(config_mod, "CONFIG_EXAMPLE_PATH", tmp_path / "nope2.yaml")

    data = config_mod.load_config()
    assert data["arms"]["a1"]["name"] == "Arm1"


def test_load_config_fallback_to_example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """load_config falls back to settings.example.yaml when no settings.yaml."""
    import nextis.config as config_mod

    example = tmp_path / "settings.example.yaml"
    example.write_text(yaml.dump({"arms": {"test": {"name": "Test"}}}))

    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "settings.yaml")
    monkeypatch.setattr(config_mod, "LEGACY_CONFIG_PATH", tmp_path / "legacy.yaml")
    monkeypatch.setattr(config_mod, "CONFIG_EXAMPLE_PATH", example)

    data = config_mod.load_config()
    assert data["arms"]["test"]["name"] == "Test"


def test_load_config_empty_when_no_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """load_config returns empty dict when no config files exist."""
    import nextis.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "nope.yaml")
    monkeypatch.setattr(config_mod, "LEGACY_CONFIG_PATH", tmp_path / "nope2.yaml")
    monkeypatch.setattr(config_mod, "CONFIG_EXAMPLE_PATH", tmp_path / "nope3.yaml")

    data = config_mod.load_config()
    assert data == {}


def test_save_config(tmp_path: Path) -> None:
    """save_config writes YAML to the given path."""
    import nextis.config as config_mod

    out = tmp_path / "out.yaml"
    config_mod.save_config({"arms": {}, "cameras": {}}, path=out)

    loaded = yaml.safe_load(out.read_text())
    assert "arms" in loaded
    assert "cameras" in loaded


# ------------------------------------------------------------------
# SystemState lifecycle tests
# ------------------------------------------------------------------


def test_system_state_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SystemState initializes and shuts down cleanly."""
    import nextis.config as config_mod
    import nextis.state as state_mod

    config_file = tmp_path / "settings.yaml"
    config_file.write_text(yaml.dump({"arms": {}, "pairings": []}))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", config_file)
    monkeypatch.setattr(config_mod, "LEGACY_CONFIG_PATH", tmp_path / "nope.yaml")
    monkeypatch.setattr(config_mod, "CONFIG_EXAMPLE_PATH", tmp_path / "nope2.yaml")

    # Ensure no stale singleton
    monkeypatch.setattr(state_mod, "_state", None)

    from nextis.state import SystemPhase, SystemState

    state = SystemState()
    state.initialize()
    assert state.phase == SystemPhase.READY
    assert state.arm_registry is not None
    assert len(state.arm_registry.arms) == 0

    state.shutdown()
    assert state.phase == SystemPhase.UNINITIALIZED


def test_system_state_with_arms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SystemState loads arm definitions from config."""
    import nextis.config as config_mod
    import nextis.state as state_mod

    config_file = tmp_path / "settings.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "arms": {
                    "test_arm": {
                        "name": "Test Arm",
                        "role": "follower",
                        "motor_type": "damiao",
                        "port": "can0",
                    },
                },
                "pairings": [],
            }
        )
    )
    monkeypatch.setattr(config_mod, "CONFIG_PATH", config_file)
    monkeypatch.setattr(config_mod, "LEGACY_CONFIG_PATH", tmp_path / "nope.yaml")
    monkeypatch.setattr(config_mod, "CONFIG_EXAMPLE_PATH", tmp_path / "nope2.yaml")
    monkeypatch.setattr(state_mod, "_state", None)

    from nextis.state import SystemState

    state = SystemState()
    state.initialize()
    assert len(state.arm_registry.arms) == 1
    assert "test_arm" in state.arm_registry.arms
    state.shutdown()


def test_get_status_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_status_dict returns phase and arm summary."""
    import nextis.config as config_mod
    import nextis.state as state_mod

    config_file = tmp_path / "settings.yaml"
    config_file.write_text(yaml.dump({"arms": {}, "pairings": []}))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", config_file)
    monkeypatch.setattr(config_mod, "LEGACY_CONFIG_PATH", tmp_path / "nope.yaml")
    monkeypatch.setattr(config_mod, "CONFIG_EXAMPLE_PATH", tmp_path / "nope2.yaml")
    monkeypatch.setattr(state_mod, "_state", None)

    from nextis.state import SystemState

    state = SystemState()
    state.initialize()
    status = state.get_status_dict()
    assert status["phase"] == "ready"
    assert status["total_arms"] == 0
    assert status["teleopActive"] is False
    assert status["recording"] is False
    state.shutdown()


# ------------------------------------------------------------------
# API route integration tests
# ------------------------------------------------------------------


def _make_isolated_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Build an isolated TestClient with tmp_path config."""
    import nextis.config as config_mod
    import nextis.state as state_mod

    configs_dir = tmp_path / "configs" / "assemblies"
    configs_dir.mkdir(parents=True)
    analytics_dir = tmp_path / "data" / "analytics"
    analytics_dir.mkdir(parents=True)

    config_file = tmp_path / "settings.yaml"
    config_file.write_text(yaml.dump({"arms": {}, "pairings": []}))

    monkeypatch.setattr(config_mod, "CONFIG_PATH", config_file)
    monkeypatch.setattr(config_mod, "LEGACY_CONFIG_PATH", tmp_path / "nope.yaml")
    monkeypatch.setattr(config_mod, "CONFIG_EXAMPLE_PATH", tmp_path / "nope2.yaml")
    monkeypatch.setattr(config_mod, "ASSEMBLIES_DIR", configs_dir)
    monkeypatch.setattr(config_mod, "ANALYTICS_DIR", analytics_dir)
    monkeypatch.setattr(state_mod, "_state", None)

    # Also patch route-module aliases (bound at import time)
    import nextis.api.routes.analytics as analytics_mod
    import nextis.api.routes.assembly as asm_mod
    import nextis.api.routes.execution as exec_mod

    monkeypatch.setattr(asm_mod, "CONFIGS_DIR", configs_dir)
    monkeypatch.setattr(exec_mod, "CONFIGS_DIR", configs_dir)
    monkeypatch.setattr(exec_mod, "ANALYTICS_DIR", analytics_dir)
    monkeypatch.setattr(analytics_mod, "CONFIGS_DIR", configs_dir)
    monkeypatch.setattr(analytics_mod, "ANALYTICS_DIR", analytics_dir)

    from nextis.api.app import app

    return TestClient(app)


def test_system_status_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /system/status returns phase and arm count."""
    client = _make_isolated_client(tmp_path, monkeypatch)
    r = client.get("/system/status")
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] == "ready"
    assert "total_arms" in data


def test_system_config_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /system/config returns the loaded config."""
    client = _make_isolated_client(tmp_path, monkeypatch)
    r = client.get("/system/config")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert "arms" in data
