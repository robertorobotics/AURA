"""Sequence planner: parsed parts + contacts → assembly steps.

Takes the output of CADParser and generates a heuristic assembly sequence.
Targets ~70% correct — user reviews and adjusts via the frontend.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from nextis.assembly.cad_parser import ParseResult
from nextis.assembly.models import (
    AssemblyGraph,
    AssemblyStep,
    ContactInfo,
    ContactType,
    Part,
    SuccessCriteria,
)
from nextis.assembly.grasp_planner import GraspPlanner
from nextis.errors import AssemblyError

logger = logging.getLogger(__name__)

# Volume threshold (m³) below which a part is considered "small"
_SMALL_PART_VOLUME = 1e-6  # ~10mm cube


class SequencePlanner:
    """Generate assembly steps and execution order from parsed CAD data.

    Sorts parts by size, assigns primitive types based on geometry
    heuristics, and wires dependencies. Tight-tolerance contacts are
    flagged as handler="policy" (needs teaching).

    Args:
        tight_tolerance: Contact clearance (metres) below which a step
            requires a learned policy instead of a primitive.
    """

    def __init__(self, tight_tolerance: float = 0.0001) -> None:
        self._tight_tolerance = tight_tolerance

    def plan(self, parse_result: ParseResult) -> AssemblyGraph:
        """Generate steps and step_order for a parsed assembly.

        Args:
            parse_result: Output from CADParser.parse().

        Returns:
            The same AssemblyGraph with steps and step_order populated.

        Raises:
            AssemblyError: If the graph has no parts.
        """
        graph = parse_result.graph
        contacts = parse_result.contacts

        if not graph.parts:
            raise AssemblyError("Cannot plan assembly with no parts")

        # Build contact adjacency and lookup map
        adjacency: dict[str, set[str]] = defaultdict(set)
        contact_map: dict[tuple[str, str], ContactInfo] = {}
        for c in contacts:
            adjacency[c.part_a].add(c.part_b)
            adjacency[c.part_b].add(c.part_a)
            contact_map[(c.part_a, c.part_b)] = c

        # Sort parts using geometric heuristics (base first, covers last)
        sorted_parts = _compute_assembly_order(graph.parts)

        steps: dict[str, AssemblyStep] = {}
        step_num = 0
        part_to_asm_step: dict[str, str] = {}

        # Base part: place it first (no pick needed)
        base = sorted_parts[0]
        base.is_base = True
        step_num += 1
        base_step_id = f"step_{step_num:03d}"
        steps[base_step_id] = AssemblyStep(
            id=base_step_id,
            name=f"Place {base.id} as base",
            part_ids=[base.id],
            dependencies=[],
            handler="primitive",
            primitive_type="place",
            primitive_params={"part_id": base.id},
            success_criteria=SuccessCriteria(type="position"),
        )
        part_to_asm_step[base.id] = base_step_id

        # Compute grasp poses for non-base parts
        GraspPlanner().plan_all(graph.parts)

        # Remaining parts: pick + assemble
        for part in sorted_parts[1:]:
            # Collect ContactInfo objects for this part
            part_contact_infos: list[ContactInfo] = []
            for cid in adjacency.get(part.id, set()):
                key = (min(part.id, cid), max(part.id, cid))
                ci = contact_map.get(key)
                if ci is not None:
                    part_contact_infos.append(ci)

            # Pick step — depends on assembly steps of contacted parts
            step_num += 1
            pick_id = f"step_{step_num:03d}"
            pick_deps = _contact_deps(part.id, adjacency, part_to_asm_step, base_step_id)
            steps[pick_id] = AssemblyStep(
                id=pick_id,
                name=f"Pick {part.id}",
                part_ids=[part.id],
                dependencies=pick_deps,
                handler="primitive",
                primitive_type="pick",
                primitive_params={
                    "part_id": part.id,
                    "grasp_index": 0 if part.grasp_points else None,
                    "approach_height": 0.05,
                },
                success_criteria=SuccessCriteria(type="force_threshold", threshold=0.5),
            )

            # Assembly step — type depends on contacts + geometry
            step_num += 1
            asm_id = f"step_{step_num:03d}"
            handler, prim_type, prim_params, criteria = self._classify_assembly_action(
                part,
                part_contact_infos,
            )

            # Parts involved: this part + any it contacts
            involved = [part.id]
            for contact_id in adjacency.get(part.id, set()):
                if contact_id not in involved:
                    involved.append(contact_id)

            steps[asm_id] = AssemblyStep(
                id=asm_id,
                name=f"Assemble {part.id}",
                part_ids=involved,
                dependencies=[pick_id],
                handler=handler,
                primitive_type=prim_type if handler == "primitive" else None,
                primitive_params=prim_params if handler == "primitive" else None,
                policy_id=None,
                success_criteria=criteria,
            )
            part_to_asm_step[part.id] = asm_id

        # Topological sort (fall back to linear order on cycle)
        try:
            step_order = self._topological_sort(steps)
        except AssemblyError:
            logger.warning(
                "Cycle detected in contact-graph dependencies for '%s'; "
                "falling back to linear step order",
                graph.id,
            )
            step_order = list(steps.keys())

        graph.steps = steps
        graph.step_order = step_order

        # Recompute layout positions now that step_order is available
        from nextis.assembly.layout import compute_layout_positions

        compute_layout_positions(graph)

        logger.info(
            "Planned %d steps for assembly '%s' (%d parts)",
            len(steps),
            graph.id,
            len(graph.parts),
        )
        return graph

    def _classify_assembly_action(
        self,
        part: Part,
        contact_infos: list[ContactInfo],
    ) -> tuple[str, str | None, dict | None, SuccessCriteria]:
        """Determine handler, primitive type, params, and criteria for a part.

        Uses enriched ContactInfo geometry for classification. Falls back
        to volume/name heuristics when no contacts are available.

        Args:
            part: The Part being classified.
            contact_infos: ContactInfo objects for this part's contacts.

        Returns:
            (handler, primitive_type, primitive_params, success_criteria)
        """
        # --- Branch 1 & 2: Coaxial contacts (clearance-based) ---
        coaxial = [ci for ci in contact_infos if ci.contact_type == ContactType.COAXIAL]
        if coaxial:
            ci = coaxial[0]
            # clearance_mm is None when not computed; treat as tight (0.0)
            clearance = ci.clearance_mm if ci.clearance_mm is not None else 0.0
            if clearance < 0.5:
                return ("policy", None, None, SuccessCriteria(type="classifier"))
            # Loose coaxial → primitive linear_insert with auto params
            return (
                "primitive",
                "linear_insert",
                {
                    "part_id": part.id,
                    "target_pose": part.position or [0.0, 0.0, 0.0],
                    "force_limit": 10.0,
                    "compliance_axes": self._compliance_from_axis(ci.insertion_axis),
                },
                SuccessCriteria(type="force_signature", pattern="snap_fit"),
            )

        # --- Branch 2.5: Face-analysis shape_class → policy ---
        sc = getattr(part, "shape_class", None)
        if sc:
            if sc == "gear_like" and contact_infos:
                return (
                    "policy",
                    None,
                    None,
                    SuccessCriteria(type="force_signature", pattern="meshing"),
                )
            if sc == "shaft" and coaxial:
                ci = coaxial[0]
                clearance = ci.clearance_mm if ci.clearance_mm is not None else 0.0
                if clearance < 0.5:
                    return ("policy", None, None, SuccessCriteria(type="classifier"))

        # --- Branch 3: Name keywords → policy ---
        name_lower = part.id.lower()
        if (
            any(kw in name_lower for kw in ("gear", "bearing", "ring", "snap", "clip"))
            and contact_infos
        ):
            return (
                "policy",
                None,
                None,
                SuccessCriteria(type="force_signature", pattern="meshing"),
            )

        # --- Branch 4: Many contact partners → policy ---
        if len(contact_infos) >= 3:
            return ("policy", None, None, SuccessCriteria(type="classifier"))

        # --- Branch 5: All planar → primitive place with auto params ---
        if contact_infos and all(ci.contact_type == ContactType.PLANAR for ci in contact_infos):
            return (
                "primitive",
                "place",
                {
                    "part_id": part.id,
                    "target_pose": part.position or [0.0, 0.0, 0.0],
                    "approach_height": 0.05,
                    "release_force": 0.2,
                },
                SuccessCriteria(type="position"),
            )

        # --- Branch 6: Very small volume → press_fit ---
        vol = _part_volume(part)
        if vol < _SMALL_PART_VOLUME:
            direction = (
                contact_infos[0].insertion_axis
                if contact_infos and contact_infos[0].insertion_axis
                else [0.0, -1.0, 0.0]
            )
            return (
                "primitive",
                "press_fit",
                {
                    "part_id": part.id,
                    "direction": direction,
                    "force_target": 15.0,
                    "max_distance": 0.02,
                },
                SuccessCriteria(type="force_threshold", threshold=15.0),
            )

        # --- Branch 7: Default → primitive place ---
        return (
            "primitive",
            "place",
            {"part_id": part.id, "target_pose": part.position or [0.0, 0.0, 0.0]},
            SuccessCriteria(type="position"),
        )

    @staticmethod
    def _topological_sort(steps: dict[str, AssemblyStep]) -> list[str]:
        """Kahn's algorithm for topological ordering of steps.

        Args:
            steps: Step definitions keyed by step ID.

        Returns:
            List of step IDs in execution order.

        Raises:
            AssemblyError: If the dependency graph has a cycle.
        """
        in_degree: dict[str, int] = {sid: 0 for sid in steps}
        children: dict[str, list[str]] = defaultdict(list)

        for sid, step in steps.items():
            for dep in step.dependencies:
                if dep in steps:
                    children[dep].append(sid)
                    in_degree[sid] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        queue.sort()  # deterministic ordering
        result: list[str] = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for child in sorted(children[node]):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(result) != len(steps):
            raise AssemblyError("Cycle detected in step dependency graph")

        return result

    @staticmethod
    def _compliance_from_axis(axis: list[float] | None) -> list[float]:
        """Build a 6-DOF compliance vector from an insertion axis.

        Returns [cx, cy, cz, 0, 0, 0] where the dominant translational
        axis is 0.0 (stiff) and others are 1.0 (compliant).

        Args:
            axis: Insertion axis [x, y, z], or None for unknown axis.

        Returns:
            Six-element compliance vector (translation + rotation).
        """
        compliance = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
        if not axis or all(v == 0.0 for v in axis):
            return compliance
        dominant_idx = max(range(3), key=lambda i: abs(axis[i]))
        compliance[dominant_idx] = 0.0
        return compliance


def _contact_deps(
    part_id: str,
    adjacency: dict[str, set[str]],
    part_to_asm_step: dict[str, str],
    base_step_id: str,
) -> list[str]:
    """Compute pick-step dependencies from the contact graph.

    For part P, returns assembly step IDs of all parts P contacts that
    have already been assigned a step. Falls back to [base_step_id]
    if no contacts exist or none of the contacted parts have steps yet.

    Args:
        part_id: ID of the part being placed.
        adjacency: Part-to-contacted-parts mapping.
        part_to_asm_step: Already-assigned part_id → assembly_step_id.
        base_step_id: Fallback step if no contact deps exist.

    Returns:
        Sorted list of dependency step IDs (deterministic ordering).
    """
    deps: set[str] = set()
    for cid in adjacency.get(part_id, set()):
        dep_step = part_to_asm_step.get(cid)
        if dep_step is not None:
            deps.add(dep_step)
    if not deps:
        deps.add(base_step_id)
    return sorted(deps)


def _compute_assembly_order(parts: dict[str, object]) -> list[object]:
    """Sort parts into assembly order using geometric heuristics.

    Rules (applied in priority order):
        1. Base part (largest volume, excluding covers) always first.
        2. Cover/lid parts (thin + wide) always last.
        3. Interior parts sorted by vertical position (Y ascending, bottom-up),
           ties broken by volume descending.

    Args:
        parts: Part catalog keyed by ID.

    Returns:
        Parts sorted in assembly order.
    """
    part_list = list(parts.values())
    if len(part_list) <= 1:
        return part_list

    # Separate covers from non-covers
    covers: list[object] = []
    non_covers: list[object] = []
    for p in part_list:
        if _is_cover(p):
            covers.append(p)
        else:
            non_covers.append(p)

    # Base = largest non-cover by volume
    if non_covers:
        base = max(non_covers, key=lambda p: _part_volume(p))
        interior = [p for p in non_covers if p.id != base.id]  # type: ignore[union-attr]
    else:
        # All parts are covers — pick largest as base
        base = max(covers, key=lambda p: _part_volume(p))
        covers = [p for p in covers if p.id != base.id]  # type: ignore[union-attr]
        interior = []

    # Sort interior by Y position ascending (bottom-up), then volume descending
    interior.sort(key=lambda p: (_assembly_height(p), -_part_volume(p)))

    # Sort covers by Y ascending
    covers.sort(key=lambda p: (_assembly_height(p), -_part_volume(p)))

    return [base] + interior + covers


def _is_cover(part: object) -> bool:
    """Detect if a part is a cover/lid (thin + wide).

    A cover has one dimension much smaller than the others (flatness < 0.15)
    and is not a known internal part type (bearing, gear, etc.).

    Args:
        part: Part to classify.

    Returns:
        True if the part appears to be a cover or lid.
    """
    from nextis.assembly.models import Part

    assert isinstance(part, Part)

    dims = part.dimensions or [0.05, 0.05, 0.05]

    # Disc: dims = [radius, height] — cover if very flat relative to diameter
    if getattr(part, "geometry", None) == "disc" and len(dims) == 2:
        name = part.id.lower()
        if any(kw in name for kw in ("bearing", "gear", "pin", "shaft", "ring", "bushing")):
            return False
        radius, height = dims
        return height / max(2 * radius, 1e-9) < 0.15

    if len(dims) < 3:
        return False

    # Internal parts are never covers regardless of shape
    name = part.id.lower()
    if any(kw in name for kw in ("bearing", "gear", "pin", "shaft", "ring", "bushing")):
        return False

    sorted_dims = sorted(dims)
    if sorted_dims[2] < 1e-9:
        return False
    flatness = sorted_dims[0] / sorted_dims[2]
    return flatness < 0.15


def _assembly_height(part: object) -> float:
    """Get the vertical position (Y coordinate) of a part for sorting.

    Args:
        part: Part to query.

    Returns:
        Y-coordinate of the part's assembled position.
    """
    from nextis.assembly.models import Part

    assert isinstance(part, Part)
    pos = part.position or [0.0, 0.0, 0.0]
    return pos[1]


def _part_volume(part: object) -> float:
    """Estimate part volume from its dimensions."""
    from nextis.assembly.models import Part

    assert isinstance(part, Part)

    dims = part.dimensions or [0.05, 0.05, 0.05]
    if len(dims) == 1:
        # Sphere: 4/3 π r³
        return (4 / 3) * 3.14159 * dims[0] ** 3
    if len(dims) == 2:
        # Cylinder: π r² h
        return 3.14159 * dims[0] ** 2 * dims[1]
    # Box: w * h * d
    return dims[0] * dims[1] * dims[2] if len(dims) >= 3 else 0.0
