"""Grasp pose computation from part geometry.

Generates candidate grasp poses for the robot gripper based on part
bounding box dimensions and geometry classification. Each grasp includes
a 6-DOF pose and an approach vector.

The gripper has 80mm max opening. Parts wider than 75mm (with 5mm safety
margin) on all graspable faces cannot be grasped and get zero candidates.
"""

from __future__ import annotations

import logging
import math
from typing import NamedTuple

from nextis.assembly.models import GraspPoint, Part

logger = logging.getLogger(__name__)

_APPROACH_DOWN: list[float] = [0.0, -1.0, 0.0]


class _GraspCandidate(NamedTuple):
    """Internal candidate with stability metric for sorting."""

    grasp: GraspPoint
    width: float  # Graspable dimension in metres (wider = more stable)


class GraspPlanner:
    """Compute candidate grasp poses for assembly parts.

    Generates grasps from bounding-box geometry only — no OCC dependency.
    Grasps are in part-local coordinates (relative to part center).

    Args:
        max_opening: Gripper max opening in metres (default 0.08).
        approach_distance: Standoff distance for approach vector (default 0.05).
        min_grasp_width: Minimum graspable dimension in metres (default 0.005).
    """

    def __init__(
        self,
        max_opening: float = 0.08,
        approach_distance: float = 0.05,
        min_grasp_width: float = 0.005,
    ) -> None:
        self._max_opening = max_opening
        self._effective_max = max_opening - 0.005  # 5mm safety margin
        self._approach_distance = approach_distance
        self._min_grasp_width = min_grasp_width

    def plan_all(self, parts: dict[str, Part]) -> None:
        """Compute and assign grasps for all parts in an assembly.

        Mutates each Part's grasp_points in-place. Skips base parts.

        Args:
            parts: Part catalog from the assembly graph.
        """
        for part in parts.values():
            if part.is_base:
                continue
            part.grasp_points = self.compute_grasps(part)

    def compute_grasps(self, part: Part) -> list[GraspPoint]:
        """Compute candidate grasps for a single part.

        Dispatches to geometry-specific methods based on part.geometry.
        Returns 0-4 grasp candidates sorted by preference (most stable first).

        Args:
            part: Part with geometry and dimensions populated.

        Returns:
            List of GraspPoint candidates. Empty if part is too large for gripper.
        """
        geo = part.geometry
        dims = part.dimensions
        if not geo or not dims:
            return []

        dispatch = {
            "box": self._grasps_box,
            "plate": self._grasps_plate,
            "cylinder": self._grasps_cylinder,
            "disc": self._grasps_disc,
            "sphere": self._grasps_sphere,
        }
        # Also handle shape_class overrides for disc/cylinder-like parts
        if part.shape_class in ("shaft",) and geo != "cylinder":
            handler = self._grasps_cylinder
        elif part.shape_class in ("gear_like",) and geo != "disc":
            handler = self._grasps_disc
        else:
            handler = dispatch.get(geo)

        if handler is None:
            logger.debug("No grasp strategy for geometry=%s part=%s", geo, part.id)
            return []

        candidates = handler(part, dims)
        # Sort by stability: wider contact area → higher priority
        candidates.sort(key=lambda c: c.width, reverse=True)
        return [c.grasp for c in candidates[:4]]

    # ------------------------------------------------------------------
    # Geometry-specific handlers
    # ------------------------------------------------------------------

    def _grasps_box(self, part: Part, dims: list[float]) -> list[_GraspCandidate]:
        """Box: grasp along the two horizontal dimensions (X and Z).

        dims = [w(X), h(Y), d(Z)]. Gripper descends along -Y.
        - ry=0: fingers along X, closing on Z (grasps d)
        - ry=pi/2: fingers along Z, closing on X (grasps w)
        """
        w = dims[0] if dims else 0.03
        h = dims[1] if len(dims) > 1 else 0.02
        d = dims[2] if len(dims) > 2 else 0.03
        half_h = h / 2
        candidates: list[_GraspCandidate] = []

        # Grasp closing on Z-dimension (fingers along X)
        if self._min_grasp_width <= d <= self._effective_max:
            candidates.append(_GraspCandidate(
                grasp=GraspPoint(
                    pose=[0.0, half_h, 0.0, 0.0, 0.0, 0.0],
                    approach=list(_APPROACH_DOWN),
                ),
                width=d,
            ))

        # Grasp closing on X-dimension (fingers along Z)
        if self._min_grasp_width <= w <= self._effective_max:
            candidates.append(_GraspCandidate(
                grasp=GraspPoint(
                    pose=[0.0, half_h, 0.0, 0.0, math.pi / 2, 0.0],
                    approach=list(_APPROACH_DOWN),
                ),
                width=w,
            ))

        return candidates

    def _grasps_plate(self, part: Part, dims: list[float]) -> list[_GraspCandidate]:
        """Plate: dims = [largest, middle, smallest] (sorted descending).

        Map to box convention: smallest → Y (height), largest → X, middle → Z.
        """
        if len(dims) < 3:
            return self._grasps_box(part, dims)
        box_dims = [dims[0], dims[2], dims[1]]  # [X=largest, Y=smallest, Z=middle]
        return self._grasps_box(part, box_dims)

    def _grasps_cylinder(self, part: Part, dims: list[float]) -> list[_GraspCandidate]:
        """Cylinder/shaft: two perpendicular grasps across diameter.

        dims = [r, h]. Gripper closes on diameter from two orientations.
        """
        r = dims[0] if dims else 0.005
        h = dims[1] if len(dims) > 1 else 0.02
        diameter = 2 * r
        half_h = h / 2
        candidates: list[_GraspCandidate] = []

        if self._min_grasp_width <= diameter <= self._effective_max:
            # Grasp 1: fingers along X, closing on Z
            candidates.append(_GraspCandidate(
                grasp=GraspPoint(
                    pose=[0.0, half_h, 0.0, 0.0, 0.0, 0.0],
                    approach=list(_APPROACH_DOWN),
                ),
                width=diameter,
            ))
            # Grasp 2: fingers along Z, closing on X (rotated 90 degrees)
            candidates.append(_GraspCandidate(
                grasp=GraspPoint(
                    pose=[0.0, half_h, 0.0, 0.0, math.pi / 2, 0.0],
                    approach=list(_APPROACH_DOWN),
                ),
                width=diameter,
            ))

        return candidates

    def _grasps_disc(self, part: Part, dims: list[float]) -> list[_GraspCandidate]:
        """Disc/gear_like: grasp along flat axis if thickness fits gripper.

        dims = [r, h] where h is the thin dimension (thickness).
        """
        h = dims[1] if len(dims) > 1 else 0.005
        half_h = h / 2
        candidates: list[_GraspCandidate] = []

        if self._min_grasp_width <= h <= self._effective_max:
            candidates.append(_GraspCandidate(
                grasp=GraspPoint(
                    pose=[0.0, half_h, 0.0, 0.0, 0.0, 0.0],
                    approach=list(_APPROACH_DOWN),
                ),
                width=h,
            ))

        return candidates

    def _grasps_sphere(self, part: Part, dims: list[float]) -> list[_GraspCandidate]:
        """Sphere: single grasp across diameter from above."""
        r = dims[0] if dims else 0.01
        diameter = 2 * r
        candidates: list[_GraspCandidate] = []

        if self._min_grasp_width <= diameter <= self._effective_max:
            candidates.append(_GraspCandidate(
                grasp=GraspPoint(
                    pose=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    approach=list(_APPROACH_DOWN),
                ),
                width=diameter,
            ))

        return candidates
