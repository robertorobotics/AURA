"""Assembly graph data models.

The assembly graph is the central data structure of the entire system.
Recording is per-step. Training is per-step. Execution walks the graph.
Analytics are per-step. If code does not reference a step_id, question why.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Part:
    """A physical part in an assembly.

    Attributes:
        id: Unique identifier for this part.
        cad_file: Path to STEP/IGES CAD file, if available.
        mesh_file: Path to tessellated mesh (glTF/GLB) for 3D viewer.
        grasp_points: List of grasp pose definitions. Each dict contains
            'pose' (6D or 7D) and 'approach' (approach vector).
    """

    id: str
    cad_file: str | None = None
    mesh_file: str | None = None
    grasp_points: list[dict] = field(default_factory=list)


@dataclass
class AssemblyStep:
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

    id: str
    name: str
    part_ids: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    handler: str = "primitive"
    primitive_type: str | None = None
    primitive_params: dict | None = None
    policy_id: str | None = None
    success_criteria: dict = field(default_factory=dict)
    max_retries: int = 3


@dataclass
class AssemblyGraph:
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
    """

    id: str
    name: str
    parts: dict[str, Part] = field(default_factory=dict)
    steps: dict[str, AssemblyStep] = field(default_factory=dict)
    step_order: list[str] = field(default_factory=list)
