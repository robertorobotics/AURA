"""Step verification dispatcher.

StepVerifier routes each step's success_criteria to the appropriate checker
function and returns a VerificationResult. Used by the execution sequencer
after step dispatch to confirm the step actually succeeded.
"""

from __future__ import annotations

import logging

from nextis.assembly.models import AssemblyStep
from nextis.perception.checks import (
    check_classifier,
    check_force_signature,
    check_force_threshold,
    check_position,
)
from nextis.perception.types import ExecutionData, VerificationResult

logger = logging.getLogger(__name__)

# Registry of criteria type → checker function.
_CHECKERS = {
    "position": check_position,
    "force_threshold": check_force_threshold,
    "force_signature": check_force_signature,
    "classifier": check_classifier,
}


class StepVerifier:
    """Dispatches step verification to the appropriate checker.

    Example::

        verifier = StepVerifier()
        result = await verifier.verify(step, exec_data)
        if not result.passed:
            # Retry or escalate to human
    """

    async def verify(self, step: AssemblyStep, exec_data: ExecutionData) -> VerificationResult:
        """Verify that a step met its success criteria.

        Args:
            step: The assembly step with success_criteria.
            exec_data: Telemetry captured after step execution.

        Returns:
            VerificationResult from the appropriate checker.
        """
        criteria_type = step.success_criteria.type

        checker = _CHECKERS.get(criteria_type)
        if checker is None:
            logger.debug(
                "No checker for criteria type '%s' on step %s — passing",
                criteria_type,
                step.id,
            )
            return VerificationResult(
                passed=True,
                confidence=0.5,
                detail=f"Unknown criteria type: {criteria_type}",
            )

        result = checker(step, exec_data)

        logger.info(
            "Verification [%s] step %s: %s (confidence=%.2f) — %s",
            criteria_type,
            step.id,
            "PASS" if result.passed else "FAIL",
            result.confidence,
            result.detail,
        )

        return result
