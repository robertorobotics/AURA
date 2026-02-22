"""Integration tests for the FastAPI routes.

Uses monkeypatching to redirect CONFIGS_DIR and ANALYTICS_DIR to tmp_path,
isolating each test from real data on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _test_assembly_data() -> dict:
    """A 2-step primitive-only assembly for API tests."""
    return {
        "id": "test_assembly",
        "name": "Test Assembly",
        "parts": {
            "part_a": {
                "id": "part_a",
                "cadFile": None,
                "meshFile": None,
                "graspPoints": [],
                "position": [0, 0, 0],
                "geometry": "box",
                "dimensions": [0.05, 0.05, 0.05],
                "color": "#AAAAAA",
            },
        },
        "steps": {
            "step_001": {
                "id": "step_001",
                "name": "Pick part A",
                "partIds": ["part_a"],
                "dependencies": [],
                "handler": "primitive",
                "primitiveType": "pick",
                "primitiveParams": {"grasp_pose": [0, 0, 0, 0, 0, 0]},
                "policyId": None,
                "successCriteria": {"type": "force_threshold", "threshold": 0.5},
                "maxRetries": 1,
            },
            "step_002": {
                "id": "step_002",
                "name": "Place part A",
                "partIds": ["part_a"],
                "dependencies": ["step_001"],
                "handler": "primitive",
                "primitiveType": "place",
                "primitiveParams": {"target_pose": [0.1, 0, 0]},
                "policyId": None,
                "successCriteria": {"type": "position"},
                "maxRetries": 1,
            },
        },
        "stepOrder": ["step_001", "step_002"],
    }


@pytest.fixture()
def isolated_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create an isolated FastAPI TestClient with tmp_path for all data dirs."""
    configs_dir = tmp_path / "configs" / "assemblies"
    configs_dir.mkdir(parents=True)
    analytics_dir = tmp_path / "data" / "analytics"
    analytics_dir.mkdir(parents=True)

    # Write fixture assembly
    (configs_dir / "test_assembly.json").write_text(json.dumps(_test_assembly_data(), indent=2))

    # Monkeypatch centralized config paths and route-module aliases
    import nextis.api.routes.analytics as analytics_mod
    import nextis.api.routes.assembly as asm_mod
    import nextis.api.routes.execution as exec_mod
    import nextis.config as config_mod
    import nextis.state as state_mod

    monkeypatch.setattr(config_mod, "ASSEMBLIES_DIR", configs_dir)
    monkeypatch.setattr(config_mod, "ANALYTICS_DIR", analytics_dir)
    monkeypatch.setattr(asm_mod, "CONFIGS_DIR", configs_dir)
    monkeypatch.setattr(exec_mod, "CONFIGS_DIR", configs_dir)
    monkeypatch.setattr(exec_mod, "ANALYTICS_DIR", analytics_dir)
    monkeypatch.setattr(analytics_mod, "CONFIGS_DIR", configs_dir)
    monkeypatch.setattr(analytics_mod, "ANALYTICS_DIR", analytics_dir)

    # Reset module-level sequencer state
    monkeypatch.setattr(exec_mod, "_sequencer", None)
    monkeypatch.setattr(exec_mod, "_analytics_store", None)

    # Reset SystemState singleton to prevent cross-test pollution
    monkeypatch.setattr(state_mod, "_state", None)

    from nextis.api.app import app

    return TestClient(app)


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------


def test_health(isolated_app: TestClient) -> None:
    r = isolated_app.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ------------------------------------------------------------------
# Assembly routes
# ------------------------------------------------------------------


def test_list_assemblies(isolated_app: TestClient) -> None:
    r = isolated_app.get("/assemblies")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    ids = [a["id"] for a in data]
    assert "test_assembly" in ids


def test_get_assembly(isolated_app: TestClient) -> None:
    r = isolated_app.get("/assemblies/test_assembly")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "test_assembly"
    assert "parts" in data
    assert "steps" in data
    assert "stepOrder" in data
    assert len(data["stepOrder"]) == 2


def test_create_assembly(isolated_app: TestClient) -> None:
    new_graph = {
        "id": "new_assembly",
        "name": "New Assembly",
        "parts": {},
        "steps": {
            "step_001": {
                "id": "step_001",
                "name": "Do something",
                "partIds": [],
                "dependencies": [],
                "handler": "primitive",
                "primitiveType": "move_to",
                "primitiveParams": {"target_pose": [0, 0, 0]},
                "policyId": None,
                "successCriteria": {"type": "position"},
                "maxRetries": 1,
            },
        },
        "stepOrder": ["step_001"],
    }
    r = isolated_app.post("/assemblies", json=new_graph)
    assert r.status_code == 201

    # Verify it appears in the list
    r2 = isolated_app.get("/assemblies")
    ids = [a["id"] for a in r2.json()]
    assert "new_assembly" in ids


def test_update_step(isolated_app: TestClient) -> None:
    r = isolated_app.patch(
        "/assemblies/test_assembly/steps/step_001",
        json={"name": "Updated pick"},
    )
    assert r.status_code == 200

    # Verify the update persisted
    r2 = isolated_app.get("/assemblies/test_assembly")
    step = r2.json()["steps"]["step_001"]
    assert step["name"] == "Updated pick"


def test_404_missing_assembly(isolated_app: TestClient) -> None:
    r = isolated_app.get("/assemblies/nonexistent")
    assert r.status_code == 404


# ------------------------------------------------------------------
# Execution routes
# ------------------------------------------------------------------


def test_start_execution(isolated_app: TestClient) -> None:
    r = isolated_app.post("/execution/start", json={"assemblyId": "test_assembly"})
    assert r.status_code == 200

    # Check that state reflects running (or already complete — stubs are fast)
    r2 = isolated_app.get("/execution/state")
    assert r2.json()["phase"] in ("running", "complete")
    assert r2.json()["assemblyId"] == "test_assembly"


# ------------------------------------------------------------------
# Upload pipeline
# ------------------------------------------------------------------


def _mock_parse_result():
    """Build a canned ParseResult for upload pipeline tests."""
    from dataclasses import dataclass
    from dataclasses import field as dc_field

    from nextis.assembly.models import (
        AssemblyGraph,
        ContactInfo,
        ContactType,
        Part,
    )

    graph = AssemblyGraph(
        id="uploaded_asm",
        name="Uploaded Assembly",
        parts={
            "base": Part(
                id="base",
                geometry="box",
                dimensions=[0.08, 0.04, 0.06],
                position=[0.0, 0.02, 0.0],
            ),
            "shaft": Part(
                id="shaft",
                geometry="cylinder",
                dimensions=[0.015, 0.10],
                position=[0.0, 0.05, 0.0],
                shape_class="shaft",
            ),
        },
    )
    contacts = [
        ContactInfo(
            part_a="base",
            part_b="shaft",
            contact_type=ContactType.COAXIAL,
            clearance_mm=0.3,
        ),
    ]

    @dataclass
    class FakeParseResult:
        graph: AssemblyGraph
        contacts: list = dc_field(default_factory=list)
        units: str = "m"
        unit_scale: float = 1.0

    return FakeParseResult(graph=graph, contacts=contacts)


def _mock_plan(parse_result):
    """Fake SequencePlanner.plan() that adds minimal steps."""
    from nextis.assembly.models import AssemblyStep, SuccessCriteria

    graph = parse_result.graph
    graph.steps = {
        "step_001": AssemblyStep(
            id="step_001",
            name="Place base",
            part_ids=["base"],
            handler="primitive",
            primitive_type="place",
            primitive_params={"target_pose": [0.0, 0.02, 0.0]},
            success_criteria=SuccessCriteria(type="position"),
        ),
    }
    graph.step_order = ["step_001"]
    return graph


def test_upload_without_api_key(
    isolated_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Upload flow works and produces valid assembly without ANTHROPIC_API_KEY."""
    import nextis.api.routes.assembly as asm_mod

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(asm_mod, "HAS_PARSER", True)

    # Mock CADParser and SequencePlanner
    class FakeParser:
        def parse(self, *args, **kwargs):
            return _mock_parse_result()

    class FakePlanner:
        def plan(self, parse_result):
            return _mock_plan(parse_result)

    monkeypatch.setattr(asm_mod, "CADParser", FakeParser)
    monkeypatch.setattr(asm_mod, "SequencePlanner", FakePlanner)

    # Create a fake STEP file
    step_file = tmp_path / "test_part.step"
    step_file.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;")

    with open(step_file, "rb") as f:
        r = isolated_app.post(
            "/assemblies/upload",
            files={"file": ("test_part.step", f, "application/octet-stream")},
        )

    assert r.status_code == 200

    # Parse NDJSON lines
    lines = [json.loads(line) for line in r.text.strip().split("\n") if line.strip()]
    assert any(msg["type"] == "complete" for msg in lines), f"No complete event in {lines}"

    complete_msg = next(msg for msg in lines if msg["type"] == "complete")
    assert "assembly" in complete_msg
    assert complete_msg["assembly"]["id"] == "uploaded_asm"


def test_upload_progress_includes_ai_stage(
    isolated_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """NDJSON stream includes ai_analysis stage (skipped without API key)."""
    import nextis.api.routes.assembly as asm_mod

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(asm_mod, "HAS_PARSER", True)

    class FakeParser:
        def parse(self, *args, **kwargs):
            return _mock_parse_result()

    class FakePlanner:
        def plan(self, parse_result):
            return _mock_plan(parse_result)

    monkeypatch.setattr(asm_mod, "CADParser", FakeParser)
    monkeypatch.setattr(asm_mod, "SequencePlanner", FakePlanner)

    step_file = tmp_path / "test_part.step"
    step_file.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;")

    with open(step_file, "rb") as f:
        r = isolated_app.post(
            "/assemblies/upload",
            files={"file": ("test_part.step", f, "application/octet-stream")},
        )

    assert r.status_code == 200

    lines = [json.loads(line) for line in r.text.strip().split("\n") if line.strip()]
    stages = [msg.get("stage") for msg in lines if msg.get("type") == "progress"]
    assert "ai_analysis" in stages, f"ai_analysis stage missing from {stages}"
