"""Layout position computation for assembly parts.

Computes pre-assembly tray positions for the 3D viewer — where each part sits
on the work surface before being picked up by the robot. Base part centered,
remaining parts in a semicircle behind it (positive Z), with grid fallback
for assemblies with more than 12 non-base parts.
"""

from __future__ import annotations

import logging
import math

from nextis.assembly.models import AssemblyGraph, Part

logger = logging.getLogger(__name__)

# Switch from semicircle to grid when non-base parts exceed this count
_SEMICIRCLE_MAX_PARTS = 12
# Minimum spacing between parts (metres)
_MIN_SPACING = 0.03
# Spacing multiplier over bbox diagonal
_SPACING_FACTOR = 1.4
# Semicircle radius multiplier over assembly radius
_RADIUS_FACTOR = 2.5
# Semicircle angular range (radians): 30° to 150°
_ARC_START = math.pi / 6
_ARC_END = 5 * math.pi / 6
# Grid layout: parts per row
_GRID_ROW_SIZE = 6
# Grid layout: row spacing multiplier over max part depth
_ROW_SPACING_FACTOR = 1.5


def compute_layout_positions(graph: AssemblyGraph) -> AssemblyGraph:
    """Assign layout_position to every part in the assembly.

    Layout rules:
        1. Identify the base part (largest by bounding volume). Set is_base=True.
        2. Place the base at the work surface center: layout_position = [0, half_height, 0].
        3. All other parts get placed in a semicircle (or grid for >12 parts)
           BEHIND the base (positive Z side), sorted by assembly order (step_order).
        4. Each part's layout Y = half its smallest dimension (resting on flattest side).
        5. Spacing between parts = max(part_bbox_diagonal, 0.03) * 1.4.
        6. The semicircle radius = assembly_radius * 2.5.

    Args:
        graph: Assembly graph with parts populated. Steps and step_order may exist.

    Returns:
        Same graph with layout_position and is_base set on all parts.
    """
    parts = list(graph.parts.values())
    if not parts:
        return graph

    # Reset is_base flags
    for p in parts:
        p.is_base = False

    # Single-part assembly: layout = assembled position
    if len(parts) == 1:
        part = parts[0]
        part.layout_position = list(part.position) if part.position else [0.0, 0.0, 0.0]
        part.is_base = True
        return graph

    # Identify base part (largest by volume)
    base = max(parts, key=_part_volume)
    base.is_base = True
    base.layout_position = [0.0, _resting_height(base), 0.0]

    # Assembly radius: max distance from centroid to any part
    assembly_radius = _compute_assembly_radius(parts)

    # Non-base parts, sorted by step_order if available
    non_base = [p for p in parts if p.id != base.id]
    non_base = _sort_by_step_order(non_base, graph.step_order, graph.steps)

    if len(non_base) <= _SEMICIRCLE_MAX_PARTS:
        _semicircle_layout(non_base, assembly_radius)
    else:
        _grid_layout(non_base, assembly_radius)

    logger.info(
        "Computed layout positions for %d parts (base=%s, mode=%s)",
        len(parts),
        base.id,
        "semicircle" if len(non_base) <= _SEMICIRCLE_MAX_PARTS else "grid",
    )
    return graph


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _part_volume(part: Part) -> float:
    """Estimate part volume from its dimensions."""
    dims = part.dimensions or [0.05, 0.05, 0.05]
    if len(dims) == 1:
        return (4 / 3) * math.pi * dims[0] ** 3  # sphere
    if len(dims) == 2:
        return math.pi * dims[0] ** 2 * dims[1]  # cylinder
    return dims[0] * dims[1] * dims[2] if len(dims) >= 3 else 0.0  # box


def _resting_height(part: Part) -> float:
    """Half the Y-extent after applying layout_rotation — how high the part sits.

    When ``layout_rotation`` is ``None`` (absent / legacy config), falls back to
    ``min(dims) / 2`` because the part orientation is unknown.  When an explicit
    rotation is provided (including identity ``[0, 0, 0]``), computes the actual
    Y-extent of the rotated bounding box via the rotation matrix second row.
    """
    dims = part.dimensions or [0.05, 0.05, 0.05]

    # No layout_rotation computed — legacy fallback: rest on thinnest side
    if part.layout_rotation is None:
        return min(dims) / 2

    rot = part.layout_rotation

    # Compute rotated Y-extent from Euler XYZ rotation matrix row 2
    dx = dims[0] / 2
    dy = (dims[1] if len(dims) > 1 else dims[0]) / 2
    dz = (dims[2] if len(dims) > 2 else dims[0]) / 2
    cx, sx = math.cos(rot[0]), math.sin(rot[0])
    cy, sy = math.cos(rot[1]), math.sin(rot[1])
    cz, sz = math.cos(rot[2]), math.sin(rot[2])
    r21 = cy * sz
    r22 = cx * cz + sx * sy * sz
    r23 = -sx * cz + cx * sy * sz
    return abs(r21) * dx + abs(r22) * dy + abs(r23) * dz


def _bbox_diagonal(part: Part) -> float:
    """Bounding box diagonal length for spacing calculations."""
    dims = part.dimensions or [0.05, 0.05, 0.05]
    if len(dims) == 1:
        return dims[0] * 2  # sphere diameter
    if len(dims) == 2:
        return math.sqrt((dims[0] * 2) ** 2 + dims[1] ** 2)  # cylinder
    return math.sqrt(sum(d**2 for d in dims[:3]))  # box


def _xz_footprint(part: Part) -> float:
    """Maximum extent of a part in the XZ ground plane."""
    dims = part.dimensions or [0.05, 0.05, 0.05]
    if len(dims) == 1:
        return dims[0] * 2  # sphere diameter
    if len(dims) == 2:
        return math.sqrt((dims[0] * 2) ** 2 + dims[1] ** 2)  # cylinder
    return math.sqrt(dims[0] ** 2 + dims[2] ** 2)  # box XZ diagonal


def _compute_assembly_radius(parts: list[Part]) -> float:
    """Max distance from centroid to any part position, floored at 0.05m."""
    n = len(parts)
    if n == 0:
        return 0.05
    cx = sum((p.position or [0, 0, 0])[0] for p in parts) / n
    cy = sum((p.position or [0, 0, 0])[1] for p in parts) / n
    cz = sum((p.position or [0, 0, 0])[2] for p in parts) / n
    max_r = 0.0
    for p in parts:
        pos = p.position or [0, 0, 0]
        dx, dy, dz = pos[0] - cx, pos[1] - cy, pos[2] - cz
        max_r = max(max_r, math.sqrt(dx * dx + dy * dy + dz * dz))
    return max(max_r, 0.05)


def _sort_by_step_order(
    parts: list[Part],
    step_order: list[str],
    steps: dict,
) -> list[Part]:
    """Sort parts by their first appearance in step_order. Unmatched parts go last."""
    if not step_order:
        return parts
    order_map: dict[str, int] = {}
    for i, step_id in enumerate(step_order):
        step = steps.get(step_id)
        if step is None:
            continue
        for pid in step.part_ids:
            if pid not in order_map:
                order_map[pid] = i
    return sorted(parts, key=lambda p: order_map.get(p.id, len(step_order)))


def _semicircle_layout(parts: list[Part], assembly_radius: float) -> None:
    """Arrange parts in a semicircle behind the base (positive Z).

    Arc spans pi/6 to 5*pi/6 in the XZ plane, centered at the origin.
    Each part's angular footprint is proportional to its XZ extent,
    preventing bounding-box overlaps between neighbours.
    """
    n = len(parts)
    if n == 0:
        return

    radius = max(assembly_radius * _RADIUS_FACTOR, _MIN_SPACING * 3)
    arc_range = _ARC_END - _ARC_START

    if n == 1:
        angle = math.pi / 2  # directly behind
        part = parts[0]
        x = radius * math.cos(angle)
        z = radius * math.sin(angle)
        y = _resting_height(part)
        part.layout_position = [round(x, 6), round(y, 6), round(z, 6)]
        return

    # Angular footprint per part + minimum gap between neighbours
    gap_angle = _MIN_SPACING / radius
    angular_widths = [_xz_footprint(p) / radius for p in parts]
    total_angle = sum(angular_widths) + gap_angle * (n - 1)

    # Grow radius if parts don't fit within the arc
    if total_angle > arc_range:
        total_footprint = sum(_xz_footprint(p) for p in parts)
        total_gaps = _MIN_SPACING * (n - 1)
        radius = (total_footprint + total_gaps) / arc_range
        gap_angle = _MIN_SPACING / radius
        angular_widths = [_xz_footprint(p) / radius for p in parts]
        total_angle = sum(angular_widths) + gap_angle * (n - 1)

    # Centre the arrangement within the arc
    offset = _ARC_START + (arc_range - total_angle) / 2

    # Place parts sequentially along the arc
    current_angle = offset
    for i, part in enumerate(parts):
        center_angle = current_angle + angular_widths[i] / 2
        x = radius * math.cos(center_angle)
        z = radius * math.sin(center_angle)
        y = _resting_height(part)
        part.layout_position = [round(x, 6), round(y, 6), round(z, 6)]
        current_angle += angular_widths[i] + gap_angle


def _grid_layout(parts: list[Part], assembly_radius: float) -> None:
    """Arrange parts in a grid behind the base for large assemblies (>12 parts).

    Rows of 6, starting at positive Z, extending further in Z for each row.
    Each row is horizontally centered.
    """
    n = len(parts)
    if n == 0:
        return

    max_diag = max(_bbox_diagonal(p) for p in parts)
    col_spacing = max(max_diag, _MIN_SPACING) * _SPACING_FACTOR
    row_spacing = max(max_diag, _MIN_SPACING) * _ROW_SPACING_FACTOR
    z_start = assembly_radius * _RADIUS_FACTOR

    for idx, part in enumerate(parts):
        row = idx // _GRID_ROW_SIZE
        col = idx % _GRID_ROW_SIZE

        # Center each row horizontally
        cols_in_row = min(_GRID_ROW_SIZE, n - row * _GRID_ROW_SIZE)
        row_width = (cols_in_row - 1) * col_spacing
        x = -row_width / 2 + col * col_spacing
        z = z_start + row * row_spacing
        y = _resting_height(part)

        part.layout_position = [round(x, 6), round(y, 6), round(z, 6)]
