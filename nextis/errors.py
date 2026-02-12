"""Nextis exception hierarchy.

All Nextis-specific exceptions inherit from NextisError. Catch specific
subclasses in business logic; only catch NextisError at top-level safety
handlers.
"""


class NextisError(Exception):
    """Base exception for all Nextis errors."""


class HardwareError(NextisError):
    """Motor communication, CAN bus, or sensor failure."""


class CalibrationError(NextisError):
    """Arm not calibrated or calibration invalid."""


class AssemblyError(NextisError):
    """Assembly graph invalid or execution failure."""


class SafetyError(NextisError):
    """Safety limit exceeded -- motors will be disabled."""
