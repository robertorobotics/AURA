"""AI-powered assembly plan analysis using Claude.

Sends an assembly graph to Claude for review with a spatial summary
of part geometry, proximity, and step completeness. Returns structured
suggestions for improving handler selection, primitive parameters,
and step ordering.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any

from nextis.assembly.models import AssemblyGraph, Part
from nextis.errors import PlannerError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — physical constraints and handler selection rules
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert robotics assembly planner for a 7-DOF robotic arm system \
(Damiao Aira Zero). You review heuristic assembly plans and suggest concrete, \
physically-grounded improvements.

## Robot Specifications
- 7-DOF arm: 3x shoulder (J8009P), 2x elbow (J4340P), 1x wrist (J4310), 1x gripper
- Workspace: ~600mm reach radius, ~400mm effective vertical clearance
- Gripper opening: 0-80mm, force range 0.1-3.0 Nm
- Position repeatability: ~0.5mm
- Joint torque: shoulder 30 Nm, elbow 15 Nm, wrist 5 Nm

## Handler Selection Rules
Use "primitive" when:
- Clearance between mating parts > 5mm
- Simple pick-and-place with no contact alignment
- Press-fits where insertion axis is well-defined and parts are rigid

Use "policy" (learned from human demonstrations) when:
- Clearance between mating parts < 2mm (tight tolerance)
- Gear meshing (teeth must align rotationally)
- Snap fits, clips, or spring-loaded contacts
- Multiple simultaneous contact points needed
- Part names contain: gear, bearing, ring, snap, clip (with contacts)

## Motion Primitives
- move_to: Joint-space motion to target pose
- pick: Approach from above + gripper close with force threshold
- place: Move to target + gripper open + retract
- guarded_move: Move in direction until force contact (probing)
- linear_insert: Insert along axis with force limit and optional compliance
- screw: Rotate wrist joint with torque monitoring
- press_fit: Push along direction until target force (interference fits)

## Force Guidelines
- Gripper grasp: 0.3-0.8 Nm (light parts 0.3, heavy parts 0.8)
- Press-fit: 5-25 Nm (typical 10-15 Nm)
- Linear insert: force_limit 5-15 Nm (bearing into housing ~10 Nm)
- Guarded move: 2-8 Nm for surface contact detection
- Screw torque: 0.5-3 Nm (M3 ~0.5, M5 ~2.0)

## Coordinate Convention
- All primitiveParams positions are in METRES.
- The spatial summary shows millimetres for readability.
- Direction vectors are unit vectors: [0,-1,0] = downward, [0,0,-1] = into page.

When you suggest primitiveParams, derive target_pose from the part's assembled \
position shown in the Part Catalog. Convert mm back to metres (divide by 1000)."""


@dataclass
class PlanSuggestion:
    """A single suggested change to the assembly plan."""

    step_id: str
    field: str
    old_value: Any
    new_value: Any
    reason: str


@dataclass
class PlanAnalysis:
    """Full analysis result from the AI planner."""

    suggestions: list[PlanSuggestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    difficulty_score: int = 5
    estimated_teaching_minutes: int = 0
    summary: str = ""


# ---------------------------------------------------------------------------
# Spatial summary helpers
# ---------------------------------------------------------------------------

_PROXIMITY_THRESHOLD_MM = 20.0


def _estimate_volume(part: Part) -> float:
    """Estimate part volume in m^3 from its dimensions."""
    dims = part.dimensions or [0.05, 0.05, 0.05]
    if len(dims) == 1:
        return (4.0 / 3.0) * math.pi * dims[0] ** 3  # sphere
    if len(dims) == 2:
        return math.pi * dims[0] ** 2 * dims[1]  # cylinder
    if len(dims) >= 3:
        return dims[0] * dims[1] * dims[2]  # box
    return 0.0


def _format_dims_mm(part: Part) -> str:
    """Format part dimensions in millimetres for display."""
    dims = part.dimensions or []
    geo = part.geometry or "unknown"
    dims_mm = [round(d * 1000, 1) for d in dims]

    if geo == "box" and len(dims_mm) >= 3:
        return f"{dims_mm[0]} x {dims_mm[1]} x {dims_mm[2]}"
    if geo == "cylinder" and len(dims_mm) >= 2:
        return f"r={dims_mm[0]}, h={dims_mm[1]}"
    if geo == "sphere" and len(dims_mm) >= 1:
        return f"r={dims_mm[0]}"
    return ", ".join(str(d) for d in dims_mm) if dims_mm else "unknown"


def _spatial_summary(graph: AssemblyGraph) -> str:
    """Build a human-readable spatial summary of the assembly.

    Converts positions/dimensions to millimetres, computes part proximity,
    and classifies step parameter completeness. Produces a compact text
    representation suitable for LLM consumption.

    Args:
        graph: The assembly graph to summarize.

    Returns:
        Multi-section text with part catalog, proximity, and step table.
    """
    lines: list[str] = []

    # --- Part Catalog ---
    parts_sorted = sorted(
        graph.parts.values(),
        key=lambda p: _estimate_volume(p),
        reverse=True,
    )

    lines.append(f"## Part Catalog ({len(graph.parts)} parts)")
    lines.append("| ID | Geometry | Dimensions (mm) | Position (mm) | Volume (mm3) |")
    lines.append("|----|----------|-----------------|---------------|-------------|")

    for p in parts_sorted:
        pos = p.position or [0.0, 0.0, 0.0]
        vol_mm3 = _estimate_volume(p) * 1e9
        pos_mm = tuple(round(v * 1000, 1) for v in pos)
        lines.append(
            f"| {p.id} | {p.geometry or 'unknown'} | {_format_dims_mm(p)} "
            f"| ({pos_mm[0]}, {pos_mm[1]}, {pos_mm[2]}) | {vol_mm3:,.0f} |"
        )

    # --- Part Proximity ---
    lines.append("")
    lines.append("## Part Proximity")

    proximity_pairs: list[tuple[str, str, float]] = []
    part_list = list(graph.parts.values())
    for i in range(len(part_list)):
        for j in range(i + 1, len(part_list)):
            p1, p2 = part_list[i], part_list[j]
            if p1.position and p2.position:
                dist_m = math.sqrt(
                    sum(
                        (a - b) ** 2
                        for a, b in zip(p1.position, p2.position, strict=False)
                    )
                )
                dist_mm = dist_m * 1000
                if dist_mm < _PROXIMITY_THRESHOLD_MM:
                    proximity_pairs.append((p1.id, p2.id, dist_mm))

    proximity_pairs.sort(key=lambda t: t[2])
    if proximity_pairs:
        for a, b, d in proximity_pairs:
            if d < 1.0:
                label = "co-located"
            elif d < 10.0:
                label = "contact"
            else:
                label = "near"
            lines.append(f"- {a} <-> {b}: {d:.1f}mm ({label})")
    else:
        lines.append("- No parts within 20mm of each other")

    # --- Step Table ---
    lines.append("")
    lines.append(f"## Assembly Steps ({len(graph.step_order)} steps)")
    lines.append("| Step | Name | Handler | Primitive | Parts | Params Status |")
    lines.append("|------|------|---------|-----------|-------|--------------|")

    for step_id in graph.step_order:
        step = graph.steps.get(step_id)
        if not step:
            continue

        # Truncate long part lists
        if len(step.part_ids) > 3:
            parts_str = ", ".join(step.part_ids[:3]) + f" +{len(step.part_ids) - 3}"
        else:
            parts_str = ", ".join(step.part_ids) if step.part_ids else "-"

        # Classify parameter completeness
        if step.handler == "policy":
            params_status = "- (policy)"
        elif step.primitive_params is None:
            params_status = "MISSING"
        elif set(step.primitive_params.keys()) == {"part_id"}:
            params_status = "part_id only"
        elif "target_pose" in step.primitive_params or "direction" in step.primitive_params:
            params_status = "complete"
        else:
            params_status = "partial"

        lines.append(
            f"| {step_id} | {step.name} | {step.handler} "
            f"| {step.primitive_type or '-'} | {parts_str} | {params_status} |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AIPlanner
# ---------------------------------------------------------------------------


class AIPlanner:
    """Analyze assembly plans using Claude.

    Builds a spatial summary of the assembly (part geometry, proximity,
    step completeness) and sends it to Claude for review. Returns
    structured suggestions including concrete primitive parameters.

    Args:
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        model: Claude model to use.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._model = model

    async def analyze(self, graph: AssemblyGraph) -> PlanAnalysis:
        """Analyze an assembly plan and return suggestions.

        Args:
            graph: The assembly graph to analyze.

        Returns:
            PlanAnalysis with suggestions, warnings, and metadata.

        Raises:
            PlannerError: If the API key is missing, API call fails,
                or response cannot be parsed.
        """
        if not self._api_key:
            raise PlannerError(
                "ANTHROPIC_API_KEY not set. Configure it in the environment "
                "or pass api_key to AIPlanner."
            )

        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:
            raise PlannerError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from e

        prompt = self._build_prompt(graph)

        try:
            client = AsyncAnthropic(api_key=self._api_key)
            message = await client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            logger.error("Anthropic API call failed: %s", e)
            raise PlannerError(f"AI analysis failed: {e}") from e

        raw_text = message.content[0].text
        logger.info(
            "AI analysis complete for %s (%d chars response)",
            graph.id,
            len(raw_text),
        )
        return self._parse_response(raw_text)

    def _build_prompt(self, graph: AssemblyGraph) -> str:
        """Build the analysis prompt with spatial summary and parameter templates."""
        spatial = _spatial_summary(graph)
        return f"""Analyze this robotic assembly plan and suggest improvements.

{spatial}

## What To Suggest

For each step that needs changes, suggest ONE change per suggestion object. \
Use one of these fields:
- **handler**: Change between "primitive" and "policy"
- **primitiveType**: Change the primitive type
- **primitiveParams**: Provide concrete parameters as a JSON object
- **successCriteria**: Update verification method as a JSON object
- **maxRetries**: Change retry count (integer)
- **name**: Improve the step description

### Parameter Templates

When suggesting primitiveParams, use these templates with ACTUAL coordinates \
from the Part Catalog above. All positions must be in METRES.

- pick: {{"part_id": "...", "grasp_index": 0, "approach_height": 0.05}}
- place: {{"target_pose": [x, y, z], "approach_height": 0.05, "release_force": 0.2}}
- press_fit: {{"direction": [0, -1, 0], "force_target": 15.0, "max_distance": 0.02}}
- linear_insert: {{"target_pose": [x, y, z], "force_limit": 10.0, \
"compliance_axes": [0, 0, 1, 0, 0, 0]}}
- guarded_move: {{"direction": [0, 0, -1], "force_threshold": 5.0, "max_distance": 0.1}}
- screw: {{"target_pose": [x, y, z], "torque_limit": 2.0, "rotations": 3.0}}

For place/insert/screw: derive target_pose from the part's assembled position in the \
Part Catalog (convert mm to metres by dividing by 1000).

Respond with ONLY a JSON object (no markdown fences, no extra text):
{{
  "suggestions": [
    {{
      "stepId": "step_XXX",
      "field": "handler|primitiveType|primitiveParams|successCriteria|maxRetries|name",
      "oldValue": "<current value (string, object, or null)>",
      "newValue": "<suggested value (string, JSON object, or integer)>",
      "reason": "brief explanation referencing part dimensions or clearances"
    }}
  ],
  "warnings": ["potential issues or risks"],
  "difficultyScore": 5,
  "estimatedTeachingMinutes": 0,
  "summary": "2-3 sentence overall assessment"
}}

Focus on:
1. Steps with MISSING or incomplete primitiveParams — fill them in with concrete values
2. Steps using "primitive" that should use "policy" (clearance < 2mm, gear meshing, snap fits)
3. Steps using "policy" that could use "primitive" (clearance > 5mm, simple pick/place)
4. Wrong primitive types for the operation described
5. Unrealistic retry counts (gear meshing needs 5+, simple pick needs only 2-3)
6. Dependency ordering issues"""

    def _parse_response(self, raw_text: str) -> PlanAnalysis:
        """Parse Claude's JSON response into a PlanAnalysis.

        Handles markdown fences defensively and uses defaults for
        missing fields. Preserves dict values for primitiveParams
        and successCriteria suggestions.
        """
        text = raw_text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            first_newline = text.find("\n")
            text = text[first_newline + 1 :] if first_newline != -1 else text[3:]
        if text.endswith("```"):
            text = text[:-3].rstrip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse AI response: %s\nRaw: %.500s", e, raw_text)
            raise PlannerError("AI returned invalid JSON response") from e

        suggestions = [
            PlanSuggestion(
                step_id=s.get("stepId", ""),
                field=s.get("field", ""),
                old_value=s.get("oldValue"),
                new_value=s.get("newValue"),
                reason=s.get("reason", ""),
            )
            for s in data.get("suggestions", [])
        ]

        return PlanAnalysis(
            suggestions=suggestions,
            warnings=data.get("warnings", []),
            difficulty_score=max(1, min(10, int(data.get("difficultyScore", 5)))),
            estimated_teaching_minutes=max(
                0, int(data.get("estimatedTeachingMinutes", 0))
            ),
            summary=data.get("summary", ""),
        )
