"""Tests for layout position computation and resting rotation."""

from __future__ import annotations

import math

import pytest

from nextis.assembly.layout import _resting_height, compute_layout_positions
from nextis.assembly.models import AssemblyGraph


def _make_graph(
    parts_data: list[dict],
    step_order: list[str] | None = None,
) -> AssemblyGraph:
    """Build a minimal AssemblyGraph from a list of part dicts."""
    parts = {}
    for p in parts_data:
        pid = p["id"]
        parts[pid] = {
            "id": pid,
            "cadFile": None,
            "meshFile": None,
            "graspPoints": [],
            "position": p.get("position", [0, 0, 0]),
            "geometry": p.get("geometry", "box"),
            "dimensions": p.get("dimensions", [0.05, 0.05, 0.05]),
            "color": "#AAA",
        }

    data = {
        "id": "test_layout",
        "name": "Test Layout",
        "parts": parts,
        "steps": {},
        "stepOrder": step_order or [],
    }
    return AssemblyGraph.model_validate(data)


def test_empty_graph_noop() -> None:
    """Empty graph returns unchanged without error."""
    graph = _make_graph([])
    result = compute_layout_positions(graph)
    assert result is graph
    assert len(graph.parts) == 0


def test_single_part_layout_equals_position() -> None:
    """Single-part assembly: layout_position = assembled position, is_base=True."""
    graph = _make_graph(
        [
            {"id": "only", "position": [0.1, 0.05, 0.2], "dimensions": [0.04, 0.04, 0.04]},
        ]
    )
    compute_layout_positions(graph)

    part = graph.parts["only"]
    assert part.layout_position == [0.1, 0.05, 0.2]
    assert part.is_base is True


def test_five_parts_base_and_distinct_positions() -> None:
    """5 parts: largest is base, non-base have distinct layout positions, all Y > 0."""
    graph = _make_graph(
        [
            {"id": "base", "dimensions": [0.1, 0.08, 0.1]},
            {"id": "p1", "dimensions": [0.02, 0.02, 0.02]},
            {"id": "p2", "dimensions": [0.03, 0.03, 0.03]},
            {"id": "p3", "dimensions": [0.01, 0.01, 0.01]},
            {"id": "p4", "dimensions": [0.015, 0.015, 0.015]},
        ]
    )
    compute_layout_positions(graph)

    # Base is correctly identified (largest by volume)
    assert graph.parts["base"].is_base is True
    assert all(not graph.parts[pid].is_base for pid in ["p1", "p2", "p3", "p4"])

    # All parts have layout_position set with 3 coordinates
    for part in graph.parts.values():
        assert part.layout_position is not None
        assert len(part.layout_position) == 3

    # All Y > 0 (resting on ground plane)
    for part in graph.parts.values():
        assert part.layout_position[1] > 0, f"{part.id} Y should be > 0"

    # All non-base positions are distinct
    positions = [tuple(graph.parts[pid].layout_position) for pid in ["p1", "p2", "p3", "p4"]]
    assert len(set(positions)) == len(positions), "Non-base parts must have distinct positions"


def test_identical_assembled_positions_get_distinct_layout() -> None:
    """Parts with the same assembled position still get distinct layout positions."""
    graph = _make_graph(
        [
            {"id": "ring", "position": [0, 0, 0], "dimensions": [0.066, 0.066, 0.024]},
            {"id": "sat_1", "position": [-0.003, 0.0, -0.002], "dimensions": [0.014, 0.014, 0.01]},
            {"id": "sat_2", "position": [-0.003, 0.0, -0.002], "dimensions": [0.014, 0.014, 0.01]},
            {"id": "sat_3", "position": [-0.003, 0.0, -0.002], "dimensions": [0.014, 0.014, 0.01]},
            {"id": "sat_4", "position": [-0.003, 0.0, -0.002], "dimensions": [0.014, 0.014, 0.01]},
        ]
    )
    compute_layout_positions(graph)

    layout_pos = [
        tuple(graph.parts[pid].layout_position) for pid in ["sat_1", "sat_2", "sat_3", "sat_4"]
    ]
    assert len(set(layout_pos)) == 4, "All satellites must have distinct layout positions"


def test_semicircle_no_overlaps_varying_sizes() -> None:
    """5 non-base parts of varying sizes in semicircle: no XZ bounding circles overlap."""
    graph = _make_graph(
        [
            {"id": "base", "dimensions": [0.1, 0.08, 0.1]},
            {"id": "big1", "dimensions": [0.05, 0.006, 0.05]},  # bearing-sized
            {"id": "big2", "dimensions": [0.042, 0.043, 0.004]},  # plate-sized
            {"id": "small1", "dimensions": [0.014, 0.014, 0.01]},  # gear-sized
            {"id": "small2", "dimensions": [0.014, 0.014, 0.01]},  # gear-sized
            {"id": "med1", "dimensions": [0.042, 0.042, 0.011]},  # medium part
        ]
    )
    compute_layout_positions(graph)

    non_base = [p for p in graph.parts.values() if not p.is_base]
    assert len(non_base) == 5

    # No pair of non-base parts should have overlapping XZ footprints
    for i, a in enumerate(non_base):
        for b in non_base[i + 1 :]:
            da = a.dimensions or [0.05, 0.05, 0.05]
            db = b.dimensions or [0.05, 0.05, 0.05]
            la = a.layout_position
            lb = b.layout_position
            assert la is not None and lb is not None
            foot_a = math.sqrt(da[0] ** 2 + (da[2] if len(da) > 2 else da[0]) ** 2)
            foot_b = math.sqrt(db[0] ** 2 + (db[2] if len(db) > 2 else db[0]) ** 2)
            dist_xz = math.sqrt((la[0] - lb[0]) ** 2 + (la[2] - lb[2]) ** 2)
            min_dist = (foot_a + foot_b) / 2
            assert dist_xz >= min_dist * 0.99, (
                f"{a.id} and {b.id} too close: dist={dist_xz:.4f} < min={min_dist:.4f}"
            )


def test_grid_layout_no_overlaps() -> None:
    """>12 non-base parts triggers grid layout; no bounding boxes overlap in XZ."""
    parts_data = [
        {"id": "base", "dimensions": [0.1, 0.1, 0.1]},
    ]
    for i in range(15):
        parts_data.append(
            {
                "id": f"p{i:02d}",
                "position": [i * 0.001, 0, 0],
                "dimensions": [0.02, 0.02, 0.02],
            }
        )
    graph = _make_graph(parts_data)
    compute_layout_positions(graph)

    # All parts have layout positions
    for part in graph.parts.values():
        assert part.layout_position is not None

    # Check no overlapping bounding boxes among non-base parts
    non_base = [p for p in graph.parts.values() if not p.is_base]
    for i, a in enumerate(non_base):
        for b in non_base[i + 1 :]:
            da = a.dimensions or [0.05, 0.05, 0.05]
            db = b.dimensions or [0.05, 0.05, 0.05]
            la = a.layout_position
            lb = b.layout_position
            assert la is not None and lb is not None
            overlap_x = abs(la[0] - lb[0]) < (da[0] + db[0]) / 2
            overlap_z = abs(la[2] - lb[2]) < (da[2] + db[2]) / 2
            assert not (overlap_x and overlap_z), f"{a.id} and {b.id} bounding boxes overlap in XZ"


# ---------------------------------------------------------------------------
# Resting rotation (OCP-dependent)
# ---------------------------------------------------------------------------


def test_resting_rotation_flat_box() -> None:
    """Box with largest face already on bottom → near-identity rotation."""
    pytest.importorskip("OCP")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    from nextis.assembly.mesh_utils import compute_resting_rotation

    # Largest face = 100x80 (XZ plane), normal in ±Y
    box = BRepPrimAPI_MakeBox(100.0, 20.0, 80.0).Shape()
    rot = compute_resting_rotation(box)
    assert isinstance(rot, list) and len(rot) == 3
    # Largest planar face normal is Y-axis → should be near-identity or π-flip
    # Either way, part rests flat with minimal tilt
    assert all(abs(r) < 0.1 or abs(abs(r) - 3.141593) < 0.1 for r in rot), (
        f"Expected near-identity rotation, got {rot}"
    )


def test_resting_rotation_tall_cylinder() -> None:
    """Tall cylinder: flat circular ends are the largest planar faces."""
    pytest.importorskip("OCP")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder

    from nextis.assembly.mesh_utils import compute_resting_rotation

    # r=5, h=100 → flat ends have area ≈ 78.5 each
    cyl = BRepPrimAPI_MakeCylinder(5.0, 100.0).Shape()
    rot = compute_resting_rotation(cyl)
    assert isinstance(rot, list) and len(rot) == 3


# ---------------------------------------------------------------------------
# Resting height semantics (None vs explicit identity)
# ---------------------------------------------------------------------------


def test_resting_height_none_vs_identity() -> None:
    """layout_rotation=None uses min(dims)/2; explicit [0,0,0] uses dims[1]/2."""
    from nextis.assembly.models import Part

    # None (legacy): min(dims)/2
    p_none = Part(id="t_none", dimensions=[0.066, 0.066, 0.024], layout_rotation=None)
    assert abs(_resting_height(p_none) - 0.012) < 1e-6

    # Explicit identity: rotated formula → dims[1]/2
    p_id = Part(id="t_id", dimensions=[0.066, 0.066, 0.024], layout_rotation=[0.0, 0.0, 0.0])
    assert abs(_resting_height(p_id) - 0.033) < 1e-6

    # Non-trivial rotation: 90° around X → Y-extent becomes original Z-extent
    p_rot = Part(
        id="t_rot",
        dimensions=[0.05, 0.006, 0.05],
        layout_rotation=[math.pi / 2, 0.0, 0.0],
    )
    assert abs(_resting_height(p_rot) - 0.025) < 1e-6
