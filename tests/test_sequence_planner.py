"""Tests for sequence planner: dependency wiring, classification, and ordering."""

from __future__ import annotations

from nextis.assembly.cad_parser import ParseResult
from nextis.assembly.models import (
    AssemblyGraph,
    ContactInfo,
    ContactType,
    Part,
)
from nextis.assembly.sequence_planner import SequencePlanner

# ---------------------------------------------------------------------------
# Assembly ordering tests (kept from original)
# ---------------------------------------------------------------------------


def test_cover_plates_assembled_last() -> None:
    """Thin, wide cover plates should be placed after internal parts."""
    parts = {
        "ring_gear": Part(
            id="ring_gear",
            position=[0, 0, 0],
            geometry="box",
            dimensions=[0.066, 0.066, 0.024],
            color="#AAA",
        ),
        "satellite_gear": Part(
            id="satellite_gear",
            position=[0.02, 0.005, 0.01],
            geometry="box",
            dimensions=[0.014, 0.014, 0.01],
            color="#BBB",
        ),
        "sun_gear": Part(
            id="sun_gear",
            position=[0, 0.005, 0],
            geometry="sphere",
            dimensions=[0.013],
            color="#CCC",
        ),
        "carrier_top": Part(
            id="carrier_top",
            position=[0, 0.05, 0],
            geometry="box",
            dimensions=[0.042, 0.042, 0.004],  # thin + wide = cover
            color="#DDD",
        ),
    }

    graph = AssemblyGraph(id="test_gearbox", name="Test Gearbox", parts=parts)
    result = ParseResult(graph=graph, contacts=[])
    planned = SequencePlanner().plan(result)

    # Find the assembly/place steps (not pick steps)
    assemble_order: list[str] = []
    for sid in planned.step_order:
        step = planned.steps[sid]
        if step.name.startswith("Assemble") or step.name.startswith("Place"):
            assemble_order.append(step.part_ids[0])

    assert assemble_order[-1] == "carrier_top", (
        f"Cover plate should be last, got order: {assemble_order}"
    )


def test_vertical_ordering_bottom_up() -> None:
    """Parts lower in the assembly (smaller Y) should be assembled before higher."""
    parts = {
        "base": Part(
            id="base",
            position=[0, 0, 0],
            geometry="box",
            dimensions=[0.1, 0.08, 0.1],
            color="#AAA",
        ),
        "low_part": Part(
            id="low_part",
            position=[0.01, 0.01, 0],
            geometry="box",
            dimensions=[0.02, 0.02, 0.02],
            color="#BBB",
        ),
        "high_part": Part(
            id="high_part",
            position=[0, 0.06, 0],
            geometry="box",
            dimensions=[0.02, 0.02, 0.02],
            color="#CCC",
        ),
    }

    graph = AssemblyGraph(id="test_vert", name="Test Vertical", parts=parts)
    result = ParseResult(graph=graph, contacts=[])
    planned = SequencePlanner().plan(result)

    assemble_order: list[str] = []
    for sid in planned.step_order:
        step = planned.steps[sid]
        if step.name.startswith("Assemble") or step.name.startswith("Place"):
            assemble_order.append(step.part_ids[0])

    low_idx = assemble_order.index("low_part")
    high_idx = assemble_order.index("high_part")
    assert low_idx < high_idx, f"Low part should come before high part, got: {assemble_order}"


# ---------------------------------------------------------------------------
# Contact-graph dependency tests
# ---------------------------------------------------------------------------


def test_contact_graph_dependencies() -> None:
    """Parts depend on assembly steps of contacted parts, not a linear chain."""
    parts = {
        "base": Part(
            id="base",
            position=[0, 0, 0],
            geometry="box",
            dimensions=[0.1, 0.05, 0.1],
            color="#AAA",
        ),
        "part_b": Part(
            id="part_b",
            position=[0, 0.02, 0],
            geometry="box",
            dimensions=[0.03, 0.03, 0.03],
            color="#BBB",
        ),
        "part_c": Part(
            id="part_c",
            position=[0, 0.05, 0],
            geometry="box",
            dimensions=[0.02, 0.02, 0.02],
            color="#CCC",
        ),
    }
    contacts = [
        ContactInfo(part_a="base", part_b="part_b", contact_type=ContactType.PLANAR),
        ContactInfo(part_a="part_b", part_b="part_c", contact_type=ContactType.PLANAR),
    ]
    graph = AssemblyGraph(id="dep_test", name="Dep Test", parts=parts)
    result = ParseResult(graph=graph, contacts=contacts)
    planned = SequencePlanner().plan(result)

    pick_b = next(s for s in planned.steps.values() if s.name == "Pick part_b")
    pick_c = next(s for s in planned.steps.values() if s.name == "Pick part_c")
    asm_b = next(s for s in planned.steps.values() if s.name == "Assemble part_b")
    base_step = next(s for s in planned.steps.values() if s.name.startswith("Place base"))

    # part_b's pick depends on base's place step (its only contact)
    assert base_step.id in pick_b.dependencies

    # part_c's pick depends on part_b's assembly step (not part_b's pick)
    assert asm_b.id in pick_c.dependencies
    assert pick_b.id not in pick_c.dependencies


def test_parallel_branches_topological_sort() -> None:
    """Two parts contacting only the base produce a valid parallel DAG."""
    parts = {
        "base": Part(
            id="base",
            position=[0, 0, 0],
            geometry="box",
            dimensions=[0.1, 0.05, 0.1],
            color="#AAA",
        ),
        "part_x": Part(
            id="part_x",
            position=[0.05, 0.02, 0],
            geometry="box",
            dimensions=[0.02, 0.02, 0.02],
            color="#BBB",
        ),
        "part_y": Part(
            id="part_y",
            position=[-0.05, 0.02, 0],
            geometry="box",
            dimensions=[0.02, 0.02, 0.02],
            color="#CCC",
        ),
        "part_d": Part(
            id="part_d",
            position=[0, 0.05, 0],
            geometry="box",
            dimensions=[0.02, 0.02, 0.02],
            color="#DDD",
        ),
    }
    contacts = [
        ContactInfo(part_a="base", part_b="part_x", contact_type=ContactType.PLANAR),
        ContactInfo(part_a="base", part_b="part_y", contact_type=ContactType.PLANAR),
        ContactInfo(part_a="part_d", part_b="part_x", contact_type=ContactType.PLANAR),
        ContactInfo(part_a="part_d", part_b="part_y", contact_type=ContactType.PLANAR),
    ]
    graph = AssemblyGraph(id="parallel_test", name="Parallel Test", parts=parts)
    result = ParseResult(graph=graph, contacts=contacts)
    planned = SequencePlanner().plan(result)

    # All steps present and valid topological order
    assert len(planned.step_order) == len(planned.steps)
    assert set(planned.step_order) == set(planned.steps.keys())

    # part_d depends on both part_x and part_y assembly steps
    pick_d = next(s for s in planned.steps.values() if s.name == "Pick part_d")
    asm_x = next(s for s in planned.steps.values() if s.name == "Assemble part_x")
    asm_y = next(s for s in planned.steps.values() if s.name == "Assemble part_y")
    assert asm_x.id in pick_d.dependencies
    assert asm_y.id in pick_d.dependencies

    # In step_order, part_d's assembly must come after both part_x and part_y
    asm_d = next(s for s in planned.steps.values() if s.name == "Assemble part_d")
    order = planned.step_order
    assert order.index(asm_d.id) > order.index(asm_x.id)
    assert order.index(asm_d.id) > order.index(asm_y.id)


def test_isolated_part_defaults_to_base() -> None:
    """Part with no contacts depends on base step."""
    parts = {
        "base": Part(
            id="base",
            position=[0, 0, 0],
            geometry="box",
            dimensions=[0.1, 0.05, 0.1],
            color="#AAA",
        ),
        "isolated": Part(
            id="isolated",
            position=[0.2, 0, 0],
            geometry="box",
            dimensions=[0.02, 0.02, 0.02],
            color="#BBB",
        ),
    }
    graph = AssemblyGraph(id="iso_test", name="Iso Test", parts=parts)
    result = ParseResult(graph=graph, contacts=[])
    planned = SequencePlanner().plan(result)

    base_step = next(s for s in planned.steps.values() if s.name.startswith("Place base"))
    pick_iso = next(s for s in planned.steps.values() if s.name == "Pick isolated")
    assert base_step.id in pick_iso.dependencies


# ---------------------------------------------------------------------------
# Classification + auto-params tests
# ---------------------------------------------------------------------------


def test_coaxial_contact_auto_params() -> None:
    """Coaxial contact with clearance >= 0.5mm gets linear_insert + compliance."""
    planner = SequencePlanner()
    part = Part(
        id="shaft",
        position=[0.0, 0.05, 0.0],
        geometry="cylinder",
        dimensions=[0.005, 0.02],
        color="#AAA",
    )
    ci = ContactInfo(
        part_a="housing",
        part_b="shaft",
        contact_type=ContactType.COAXIAL,
        insertion_axis=[0.0, 1.0, 0.0],
        clearance_mm=1.0,
    )
    handler, prim_type, params, criteria = planner._classify_assembly_action(part, [ci])

    assert handler == "primitive"
    assert prim_type == "linear_insert"
    assert params is not None
    assert "compliance_axes" in params
    # Y-axis dominant (index 1) → stiff along Y
    assert params["compliance_axes"][1] == 0.0
    assert params["compliance_axes"][0] == 1.0
    assert params["compliance_axes"][2] == 1.0
    assert params["target_pose"] == [0.0, 0.05, 0.0]


def test_planar_contact_gets_place() -> None:
    """All-planar contacts produce a place primitive with auto params."""
    planner = SequencePlanner()
    part = Part(
        id="cover",
        position=[0.0, 0.03, 0.0],
        geometry="box",
        dimensions=[0.05, 0.002, 0.05],
        color="#AAA",
    )
    ci = ContactInfo(
        part_a="base",
        part_b="cover",
        contact_type=ContactType.PLANAR,
        normal=[0.0, 1.0, 0.0],
    )
    handler, prim_type, params, criteria = planner._classify_assembly_action(part, [ci])

    assert handler == "primitive"
    assert prim_type == "place"
    assert params is not None
    assert "approach_height" in params
    assert "release_force" in params
    assert params["part_id"] == "cover"


def test_cycle_detection_fallback() -> None:
    """Cycle in step graph triggers fallback to linear order, no crash."""
    from nextis.errors import AssemblyError

    parts = {
        "base": Part(
            id="base",
            position=[0, 0, 0],
            geometry="box",
            dimensions=[0.1, 0.05, 0.1],
            color="#AAA",
        ),
        "part_b": Part(
            id="part_b",
            position=[0, 0.02, 0],
            geometry="box",
            dimensions=[0.03, 0.03, 0.03],
            color="#BBB",
        ),
    }
    graph = AssemblyGraph(id="cycle_test", name="Cycle Test", parts=parts)
    result = ParseResult(graph=graph, contacts=[])

    planner = SequencePlanner()

    # Monkeypatch topo sort to simulate cycle detection
    def raising_sort(steps: dict) -> list[str]:
        raise AssemblyError("Cycle detected in step dependency graph")

    planner._topological_sort = raising_sort  # type: ignore[method-assign]

    # Should not raise — fallback produces all steps in linear order
    planned = planner.plan(result)
    assert len(planned.step_order) == len(planned.steps)
    assert set(planned.step_order) == set(planned.steps.keys())
