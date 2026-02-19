"""Tests for automatic grasp planning from part geometry."""

from __future__ import annotations

import math

from nextis.assembly.grasp_planner import GraspPlanner
from nextis.assembly.models import Part


def test_box_two_grasps() -> None:
    """A graspable box (0.03, 0.02, 0.04) gets 2 grasp candidates."""
    part = Part(
        id="block",
        geometry="box",
        dimensions=[0.03, 0.02, 0.04],
        position=[0, 0.01, 0],
    )
    grasps = GraspPlanner().compute_grasps(part)

    assert len(grasps) == 2
    # Both should approach from above
    for g in grasps:
        assert g.approach == [0.0, -1.0, 0.0]
    # Sorted by width descending: d=0.04 first, w=0.03 second
    assert grasps[0].pose[4] == 0.0  # ry=0 → fingers X, closing on Z=0.04
    assert abs(grasps[1].pose[4] - math.pi / 2) < 1e-9  # ry=pi/2 → closing on X=0.03


def test_oversized_part_no_grasps() -> None:
    """A box wider than 75mm on both horizontal faces gets 0 grasps."""
    part = Part(
        id="big_block",
        geometry="box",
        dimensions=[0.1, 0.05, 0.1],
        position=[0, 0.025, 0],
    )
    grasps = GraspPlanner().compute_grasps(part)

    assert len(grasps) == 0


def test_cylinder_perpendicular_grasps() -> None:
    """A cylinder with diameter < 80mm gets grasps perpendicular to axis."""
    part = Part(
        id="pin",
        geometry="cylinder",
        dimensions=[0.003, 0.02],  # r=3mm, h=20mm → diameter=6mm
        position=[0, 0.01, 0],
    )
    grasps = GraspPlanner().compute_grasps(part)

    assert len(grasps) == 2
    # Both at top of cylinder (h/2 = 0.01)
    for g in grasps:
        assert g.pose[1] == 0.01
    # Orientations differ by pi/2 in ry
    ry_values = sorted(g.pose[4] for g in grasps)
    assert abs(ry_values[0] - 0.0) < 1e-9
    assert abs(ry_values[1] - math.pi / 2) < 1e-6


def test_base_part_skipped() -> None:
    """A part with is_base=True gets 0 grasps via plan_all()."""
    parts = {
        "base": Part(
            id="base",
            geometry="box",
            dimensions=[0.06, 0.04, 0.06],
            position=[0, 0, 0],
            is_base=True,
        ),
        "small": Part(
            id="small",
            geometry="box",
            dimensions=[0.03, 0.02, 0.03],
            position=[0, 0.02, 0],
        ),
    }
    GraspPlanner().plan_all(parts)

    assert len(parts["base"].grasp_points) == 0
    assert len(parts["small"].grasp_points) > 0


def test_approach_vector_normalized() -> None:
    """All returned approach vectors have magnitude 1.0."""
    part = Part(
        id="part",
        geometry="box",
        dimensions=[0.02, 0.02, 0.02],
        position=[0, 0.01, 0],
    )
    grasps = GraspPlanner().compute_grasps(part)

    assert len(grasps) > 0
    for g in grasps:
        magnitude = math.sqrt(sum(c * c for c in g.approach))
        assert abs(magnitude - 1.0) < 1e-9


def test_grasp_within_opening() -> None:
    """No grasp's target dimension exceeds max_opening."""
    part = Part(
        id="mixed",
        geometry="box",
        dimensions=[0.07, 0.02, 0.09],  # w=70mm fits, d=90mm too wide
        position=[0, 0.01, 0],
    )
    grasps = GraspPlanner().compute_grasps(part)

    # Only the w=70mm grasp survives (d=90mm > 75mm effective max)
    assert len(grasps) == 1
    # Surviving grasp: fingers along Z (ry=pi/2), closing on X=70mm
    assert abs(grasps[0].pose[4] - math.pi / 2) < 1e-6


def test_disc_thickness_grasp() -> None:
    """A disc (r=0.02, h=0.008) gets a grasp along its flat axis."""
    part = Part(
        id="washer",
        geometry="disc",
        dimensions=[0.02, 0.008],  # r=20mm, h=8mm (above 5mm min_grasp_width)
        position=[0, 0.004, 0],
    )
    grasps = GraspPlanner().compute_grasps(part)

    assert len(grasps) == 1
    assert grasps[0].approach == [0.0, -1.0, 0.0]
