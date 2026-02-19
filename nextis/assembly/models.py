"""Assembly graph data models.

The assembly graph is the central data structure of the entire system.
Recording is per-step. Training is per-step. Execution walks the graph.
Analytics are per-step. If code does not reference a step_id, question why.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class GraspPoint(BaseModel):
    """A grasp pose definition with approach vector."""

    model_config = ConfigDict(populate_by_name=True)

    pose: list[float]
    approach: list[float]


class ContactType(str, Enum):  # noqa: UP042
    """Classification of the geometric relationship between two contacting parts."""

    COAXIAL = "coaxial"
    PLANAR = "planar"
    POINT = "point"
    LINE = "line"
    COMPLEX = "complex"


class ContactInfo(BaseModel):
    """Geometric description of a contact between two assembly parts.

    Provides geometric details about the contact relationship including
    closest points, surface normal, contact type classification, and
    derived insertion axis. Used by the sequence planner for handler
    selection and by the AI planner for spatial reasoning.

    Attributes:
        part_a: ID of the first part (lexicographically smaller).
        part_b: ID of the second part.
        distance: Minimum distance between shapes (metres). 0.0 = touching.
        normal: Unit normal vector [x, y, z] from part_a toward part_b.
        contact_point_a: Closest point on part_a [x, y, z] in metres.
        contact_point_b: Closest point on part_b [x, y, z] in metres.
        contact_type: Classification of the contact geometry.
        insertion_axis: Estimated insertion direction [x, y, z], or None.
        clearance_mm: Estimated radial clearance in mm (coaxial), or None.
        area_class: "large" (>100mm2), "medium" (10-100mm2), "small", or None.
    """

    model_config = ConfigDict(populate_by_name=True)

    part_a: str = Field(alias="partA")
    part_b: str = Field(alias="partB")
    distance: float = 0.0
    normal: list[float] = Field(default_factory=lambda: [0.0, 1.0, 0.0])
    contact_point_a: list[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0], alias="contactPointA"
    )
    contact_point_b: list[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0], alias="contactPointB"
    )
    contact_type: ContactType = Field(ContactType.COMPLEX, alias="contactType")
    insertion_axis: list[float] | None = Field(None, alias="insertionAxis")
    clearance_mm: float | None = Field(None, alias="clearanceMm")
    area_class: str | None = Field(None, alias="areaClass")


class Part(BaseModel):
    """A physical part in an assembly.

    Attributes:
        id: Unique identifier for this part.
        cad_file: Path to STEP/IGES CAD file, if available.
        mesh_file: Path to tessellated mesh (glTF/GLB) for 3D viewer.
        grasp_points: List of grasp pose definitions.
        position: [x, y, z] assembled position in metres.
        rotation: [rx, ry, rz] euler angles in radians.
        geometry: Placeholder shape — "box", "cylinder", "sphere", "disc", or "plate".
        dimensions: Shape-specific dims (box=[w,h,d], cylinder=[r,h], sphere=[r],
            disc=[r,h], plate=[l,w,t]).
        shape_class: Face-analysis classification — "shaft", "housing", "gear_like",
            "plate", "block", or "complex". None if analysis was not performed.
        face_stats: Percentage of total surface area by face type (e.g.
            {"cylindrical": 65.2, "planar": 30.1}). None if not computed.
        color: Hex colour string for placeholder rendering.
        layout_position: [x, y, z] pre-assembly tray position in metres, or None.
        is_base: Whether this part is the base/fixture that stays centered.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    cad_file: str | None = Field(None, alias="cadFile")
    mesh_file: str | None = Field(None, alias="meshFile")
    grasp_points: list[GraspPoint] = Field(default_factory=list, alias="graspPoints")
    position: list[float] | None = None
    rotation: list[float] | None = None
    geometry: str | None = None
    dimensions: list[float] | None = None
    shape_class: str | None = Field(None, alias="shapeClass")
    face_stats: dict[str, float] | None = Field(None, alias="faceStats")
    color: str | None = None
    layout_position: list[float] | None = Field(None, alias="layoutPosition")
    layout_rotation: list[float] | None = Field(None, alias="layoutRotation")
    is_base: bool = Field(False, alias="isBase")


class SuccessCriteria(BaseModel):
    """How to verify that an assembly step completed successfully."""

    model_config = ConfigDict(populate_by_name=True)

    type: str
    threshold: float | None = None
    model: str | None = None
    pattern: str | None = None


class AssemblyStep(BaseModel):
    """A single step in an assembly sequence.

    Each step is either handled by a parameterized primitive (pick, place,
    guarded_insert, etc.) or by a learned policy. The handler field
    determines which.

    Attributes:
        id: Unique step identifier (e.g., "step_001").
        name: Human-readable description (e.g., "Insert bearing into housing").
        part_ids: IDs of parts involved in this step.
        dependencies: Step IDs that must complete before this step can run.
        handler: Either "primitive" or "policy".
        primitive_type: Primitive name when handler is "primitive".
        primitive_params: Parameters for the primitive (target_pose, force, etc.).
        policy_id: Checkpoint path when handler is "policy".
        success_criteria: How to verify step completion.
        max_retries: Maximum retry attempts before escalating to human.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    part_ids: list[str] = Field(default_factory=list, alias="partIds")
    dependencies: list[str] = Field(default_factory=list)
    handler: str = "primitive"
    primitive_type: str | None = Field(None, alias="primitiveType")
    primitive_params: dict | None = Field(None, alias="primitiveParams")
    policy_id: str | None = Field(None, alias="policyId")
    success_criteria: SuccessCriteria = Field(
        default_factory=lambda: SuccessCriteria(type="position"),
        alias="successCriteria",
    )
    max_retries: int = Field(3, alias="maxRetries")


class AssemblyGraph(BaseModel):
    """A complete assembly definition.

    Contains the part catalog, step definitions, and topologically sorted
    execution order. This is the spine of the entire system -- execution,
    recording, training, and analytics all index into this structure.

    Attributes:
        id: Unique assembly identifier.
        name: Human-readable assembly name.
        parts: Part catalog keyed by part ID.
        steps: Step definitions keyed by step ID.
        step_order: Topologically sorted list of step IDs for execution.
        contacts: Inter-part contact pairs from CAD analysis.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    parts: dict[str, Part] = Field(default_factory=dict)
    steps: dict[str, AssemblyStep] = Field(default_factory=dict)
    step_order: list[str] = Field(default_factory=list, alias="stepOrder")
    unit_scale: float = Field(1.0, alias="unitScale")
    contacts: list[ContactInfo] = Field(default_factory=list)

    @classmethod
    def from_json_file(cls, path: Path) -> AssemblyGraph:
        """Load an assembly graph from a JSON file.

        Args:
            path: Path to the JSON file.

        Returns:
            Parsed AssemblyGraph instance.
        """
        data = json.loads(path.read_text())
        return cls.model_validate(data)

    def to_json_file(self, path: Path) -> None:
        """Save the assembly graph to a JSON file with camelCase keys.

        Args:
            path: Destination file path.
        """
        path.write_text(self.model_dump_json(by_alias=True, indent=2) + "\n")
        logger.info("Saved assembly %s to %s", self.id, path)
