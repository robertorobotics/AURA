"""Assembly CRUD routes.

Assemblies are stored as JSON files in configs/assemblies/.
STEP file uploads are parsed into assemblies via CADParser.
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from nextis.api.schemas import AssemblySummary, PlanAnalysisResponse, PlanSuggestionResponse
from nextis.assembly.models import AssemblyGraph
from nextis.errors import CADParseError, PlannerError

logger = logging.getLogger(__name__)

try:
    from nextis.assembly.cad_parser import CADParser
    from nextis.assembly.sequence_planner import SequencePlanner

    HAS_PARSER = True
except Exception:
    HAS_PARSER = False

router = APIRouter()

CONFIGS_DIR = Path(__file__).resolve().parents[3] / "configs" / "assemblies"
MESHES_DIR = Path(__file__).resolve().parents[3] / "data" / "meshes"


def _find_assembly_path(assembly_id: str) -> Path:
    """Resolve an assembly ID to its JSON file path.

    Args:
        assembly_id: The assembly identifier.

    Returns:
        Path to the JSON file.

    Raises:
        HTTPException: If the assembly file does not exist.
    """
    path = CONFIGS_DIR / f"{assembly_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Assembly '{assembly_id}' not found")
    return path


def _load_assembly(assembly_id: str) -> AssemblyGraph:
    """Load and validate an assembly from disk."""
    path = _find_assembly_path(assembly_id)
    return AssemblyGraph.from_json_file(path)


@router.get("", response_model=list[AssemblySummary])
async def list_assemblies() -> list[AssemblySummary]:
    """List all assemblies (id + name only)."""
    summaries: list[AssemblySummary] = []
    for json_file in sorted(CONFIGS_DIR.glob("*.json")):
        try:
            graph = AssemblyGraph.from_json_file(json_file)
            summaries.append(AssemblySummary(id=graph.id, name=graph.name))
        except Exception:
            logger.warning("Failed to load assembly from %s", json_file, exc_info=True)
    return summaries


@router.get("/{assembly_id}")
async def get_assembly(assembly_id: str) -> dict[str, Any]:
    """Get the full assembly graph by ID."""
    graph = _load_assembly(assembly_id)
    return graph.model_dump(by_alias=True)


@router.post("", status_code=201)
async def create_assembly(graph: AssemblyGraph) -> dict[str, str]:
    """Create a new assembly from a full graph definition."""
    path = CONFIGS_DIR / f"{graph.id}.json"
    if path.exists():
        raise HTTPException(status_code=409, detail=f"Assembly '{graph.id}' already exists")
    graph.to_json_file(path)
    logger.info("Created assembly %s", graph.id)
    return {"status": "created", "id": graph.id}


@router.patch("/{assembly_id}/steps/{step_id}")
async def update_step(
    assembly_id: str,
    step_id: str,
    updates: dict[str, Any],
) -> dict[str, str]:
    """Partially update a single step in an assembly."""
    graph = _load_assembly(assembly_id)
    if step_id not in graph.steps:
        raise HTTPException(status_code=404, detail=f"Step '{step_id}' not found")

    # Deserialize any JSON-encoded dict fields before Pydantic validation
    for key in ("primitiveParams", "primitive_params", "successCriteria", "success_criteria"):
        if key in updates and isinstance(updates[key], str):
            with contextlib.suppress(json.JSONDecodeError):
                updates[key] = json.loads(updates[key])

    step = graph.steps[step_id]
    updated_data = step.model_dump(by_alias=True)
    updated_data.update(updates)
    graph.steps[step_id] = type(step).model_validate(updated_data)

    path = CONFIGS_DIR / f"{assembly_id}.json"
    graph.to_json_file(path)
    logger.info("Updated step %s in assembly %s", step_id, assembly_id)
    return {"status": "updated"}


@router.patch("/{assembly_id}")
async def update_assembly(
    assembly_id: str,
    updates: dict[str, Any],
) -> dict[str, str]:
    """Update assembly-level metadata (currently: name only).

    Args:
        assembly_id: The assembly to update.
        updates: Dict with fields to update. Supports ``name``.
    """
    graph = _load_assembly(assembly_id)

    name = updates.get("name")
    if name is not None:
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=422, detail="Name must be a non-empty string")
        if len(name) > 100:
            raise HTTPException(status_code=422, detail="Name must be 100 characters or fewer")
        graph.name = name.strip()

    path = CONFIGS_DIR / f"{assembly_id}.json"
    graph.to_json_file(path)
    logger.info("Updated assembly metadata for %s", assembly_id)
    return {"status": "updated"}


@router.delete("/{assembly_id}")
async def delete_assembly(assembly_id: str) -> dict[str, str]:
    """Delete an assembly and its associated mesh files."""
    path = _find_assembly_path(assembly_id)
    path.unlink()

    mesh_dir = MESHES_DIR / assembly_id
    if mesh_dir.is_dir():
        shutil.rmtree(mesh_dir)

    logger.info("Deleted assembly %s", assembly_id)
    return {"status": "deleted", "id": assembly_id}


@router.post("/upload", status_code=201)
async def upload_step_file(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
    """Parse a STEP file and create an assembly with GLB meshes.

    Accepts a multipart form upload of a .step/.stp file. Parses geometry,
    generates GLB meshes, plans an initial assembly sequence, and returns
    the full AssemblyGraph.

    Args:
        file: Uploaded STEP file (.step or .stp).

    Returns:
        Full assembly graph with camelCase keys.
    """
    if not HAS_PARSER:
        raise HTTPException(
            status_code=400,
            detail="CAD parsing unavailable. Install pythonocc-core via conda.",
        )

    filename = file.filename or "unknown.step"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".step", ".stp"}:
        raise HTTPException(status_code=400, detail=f"Expected .step/.stp file, got '{suffix}'")

    # Save upload to temp dir, preserving original filename so the parser
    # derives the correct assembly_id from the file stem.
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / filename
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        parser = CADParser()
        mesh_dir = MESHES_DIR / tmp_path.stem.lower().replace(" ", "_").replace("-", "_")

        parse_result = parser.parse(tmp_path, mesh_dir, assembly_name=tmp_path.stem)

        planner = SequencePlanner()
        graph = planner.plan(parse_result)

        # Auto-assign handlers based on primitive_type
        from nextis.assembly.sequence_planner import assign_handlers

        graph = assign_handlers(graph)

        json_path = CONFIGS_DIR / f"{graph.id}.json"
        graph.to_json_file(json_path)
        logger.info("Created assembly '%s' from uploaded STEP file", graph.id)
        return graph.model_dump(by_alias=True)

    except HTTPException:
        raise
    except CADParseError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error("STEP upload failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal parsing error") from e
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/{assembly_id}/analyze", response_model=PlanAnalysisResponse)
async def analyze_assembly(
    assembly_id: str,
    apply: bool = False,
) -> PlanAnalysisResponse:
    """Run AI analysis on an assembly plan.

    Sends the assembly graph to Claude for review and returns suggested
    improvements to step ordering, handler selection, and parameters.

    Args:
        assembly_id: The assembly to analyze.
        apply: If True, automatically apply safe suggestions and save.
    """
    graph = _load_assembly(assembly_id)

    try:
        from nextis.assembly.ai_planner import AIPlanner

        planner = AIPlanner()
        analysis = await planner.analyze(graph)
    except PlannerError as e:
        if "not set" in str(e) or "not installed" in str(e):
            raise HTTPException(status_code=503, detail=str(e)) from e
        raise HTTPException(status_code=422, detail=str(e)) from e

    if apply and analysis.suggestions:
        _apply_suggestions(graph, analysis.suggestions)
        path = CONFIGS_DIR / f"{assembly_id}.json"
        graph.to_json_file(path)
        logger.info("Applied %d AI suggestions to %s", len(analysis.suggestions), assembly_id)

    return PlanAnalysisResponse(
        suggestions=[
            PlanSuggestionResponse(
                step_id=s.step_id,
                field=s.field,
                old_value=s.old_value,
                new_value=s.new_value,
                reason=s.reason,
            )
            for s in analysis.suggestions
        ],
        warnings=analysis.warnings,
        difficulty_score=analysis.difficulty_score,
        estimated_teaching_minutes=analysis.estimated_teaching_minutes,
        summary=analysis.summary,
    )


_VALID_PRIMITIVE_TYPES = {
    "move_to", "pick", "place", "guarded_move", "linear_insert", "screw", "press_fit",
}
_VALID_CRITERIA_TYPES = {"position", "force_threshold", "force_signature", "classifier"}


def _apply_suggestions(
    graph: AssemblyGraph,
    suggestions: list[Any],
) -> None:
    """Apply AI suggestions to the assembly graph in-place.

    Modifies whitelisted fields: handler, primitiveType, primitiveParams,
    successCriteria, maxRetries, name. Validates types and values before
    applying. Skips unknown step_ids or unrecognized fields.
    """
    field_map = {
        "handler": "handler",
        "primitiveType": "primitive_type",
        "primitive_type": "primitive_type",
        "primitiveParams": "primitive_params",
        "primitive_params": "primitive_params",
        "successCriteria": "success_criteria",
        "success_criteria": "success_criteria",
        "maxRetries": "max_retries",
        "max_retries": "max_retries",
        "name": "name",
    }

    for s in suggestions:
        if s.step_id not in graph.steps:
            logger.warning("Skipping suggestion for unknown step %s", s.step_id)
            continue

        attr = field_map.get(s.field)
        if attr is None:
            logger.warning("Skipping suggestion for unsupported field %s", s.field)
            continue

        step = graph.steps[s.step_id]
        current = getattr(step, attr)
        value: Any = s.new_value

        # Type coercion
        if attr == "max_retries":
            try:
                value = int(value)
            except (ValueError, TypeError):
                logger.warning("Skipping invalid max_retries value: %s", value)
                continue
        elif attr in ("primitive_params", "success_criteria") and isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                logger.warning("Skipping non-JSON %s value: %.100s", attr, value)
                continue

        # Validate primitive_params
        if attr == "primitive_params":
            if step.handler == "policy" and value is not None:
                logger.warning("Skipping primitiveParams for policy step %s", s.step_id)
                continue
            if not isinstance(value, (dict, type(None))):
                logger.warning("Skipping non-dict primitiveParams for %s", s.step_id)
                continue

        # Validate success_criteria
        if (
            attr == "success_criteria"
            and isinstance(value, dict)
            and value.get("type") not in _VALID_CRITERIA_TYPES
        ):
            logger.warning(
                "Skipping unknown criteria type '%s' for %s",
                value.get("type"),
                s.step_id,
            )
            continue

        # Validate primitive_type
        if attr == "primitive_type" and value is not None and value not in _VALID_PRIMITIVE_TYPES:
            logger.warning("Skipping unknown primitive_type '%s'", value)
            continue

        setattr(step, attr, value)
        logger.info("Applied: %s.%s: %s -> %s", s.step_id, attr, current, value)
