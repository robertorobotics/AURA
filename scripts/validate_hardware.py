"""Hardware validation script -- exercises motion primitives on a physical or mock arm.

Usage:
    python scripts/validate_hardware.py --arm-id aira_zero --mock
    python scripts/validate_hardware.py --arm-id aira_zero --port can0
    python scripts/validate_hardware.py --check-only

Runs 5 motion primitives in sequence, logs results, and writes a JSON summary
to ``data/hardware_validation/{arm_id}_{timestamp}.json``.

With ``--check-only``, validates connectivity for all configured arms without
running primitives.

Exit code 0 if all primitives succeed, 1 if any fail.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure project root and lerobot/src are on PYTHONPATH
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
LEROBOT_SRC = str(Path(__file__).resolve().parents[1] / "lerobot" / "src")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LEROBOT_SRC)
os.environ["PYTHONPATH"] = (
    LEROBOT_SRC + os.pathsep + PROJECT_ROOT + os.pathsep + os.environ.get("PYTHONPATH", "")
)

from nextis.control.motion_helpers import PrimitiveResult  # noqa: E402
from nextis.control.primitives import PrimitiveLibrary  # noqa: E402
from nextis.hardware.calibration import CalibrationManager  # noqa: E402

logger = logging.getLogger("validate_hardware")

# ---------------------------------------------------------------------------
# Validation steps
# ---------------------------------------------------------------------------

VALIDATION_STEPS: list[dict] = [
    {
        "name": "move_to_home",
        "primitive": "move_to",
        "params": {"target_pose": [0.0] * 7, "velocity": 0.3},
    },
    {
        "name": "move_to_offset",
        "primitive": "move_to",
        "params": {
            "target_pose": [0.1, 0.2, 0.1, 0.0, 0.0, 0.0, 0.0],
            "velocity": 0.5,
        },
    },
    {
        "name": "pick",
        "primitive": "pick",
        "params": {"grasp_pose": [0.0] * 6, "approach_height": 0.05},
    },
    {
        "name": "place",
        "primitive": "place",
        "params": {
            "target_pose": [0.0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0],
            "approach_height": 0.05,
        },
    },
    {
        "name": "guarded_move",
        "primitive": "guarded_move",
        "params": {
            "direction": [0, -1, 0],
            "force_threshold": 5.0,
            "max_distance": 0.1,
        },
    },
]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _get_robot(args: argparse.Namespace) -> object | None:
    """Create a robot instance based on CLI arguments.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Robot instance for real hardware, or None for mock mode.
        Primitives treat ``robot=None`` as mock and return synthetic success.
    """
    if args.mock:
        logger.info("Using mock mode (robot=None) for validation")
        return None

    # Real hardware path: attempt to connect via arm registry
    try:
        from nextis.hardware.arm_registry import ArmRegistryService

        registry = ArmRegistryService()
        arm = registry.get_arm(args.arm_id)
        if arm is None:
            logger.error(
                "Arm '%s' not found in registry. "
                "Register it in configs/arms/settings.yaml or use --mock.",
                args.arm_id,
            )
            sys.exit(1)

        result = registry.connect_arm(args.arm_id)
        if not result.get("success"):
            logger.error(
                "Failed to connect arm '%s': %s",
                args.arm_id,
                result.get("error", "unknown error"),
            )
            sys.exit(1)

        instance = registry.get_arm_instance(args.arm_id)
        if instance is None:
            logger.error("Arm '%s' connected but no robot instance available", args.arm_id)
            sys.exit(1)

        logger.info("Connected to real arm '%s' on port %s", args.arm_id, args.port)
        return instance
    except ImportError:
        logger.error("ArmRegistryService not available. Use --mock for testing.")
        sys.exit(1)


def _format_result(step_name: str, result: PrimitiveResult) -> dict:
    """Format a primitive result into a summary dict.

    Args:
        step_name: Human-readable name for the validation step.
        result: Primitive execution result.

    Returns:
        Summary dict for JSON output.
    """
    return {
        "name": step_name,
        "success": result.success,
        "duration_ms": round(result.duration_ms, 2),
        "actual_force": round(result.actual_force, 4),
        "error_message": result.error_message,
    }


def _write_summary(arm_id: str, results: list[dict]) -> Path:
    """Write validation summary to JSON file.

    Args:
        arm_id: Arm identifier.
        results: List of per-step result dicts.

    Returns:
        Path to the written summary file.
    """
    output_dir = Path("data/hardware_validation")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    output_path = output_dir / f"{arm_id}_{timestamp}.json"

    overall_pass = all(r["success"] for r in results)
    summary = {
        "arm_id": arm_id,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "results": results,
        "overall_pass": overall_pass,
    }

    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    return output_path


async def _run_validation(args: argparse.Namespace) -> bool:
    """Execute the validation sequence.

    Args:
        args: Parsed command-line arguments.

    Returns:
        True if all primitives passed, False otherwise.
    """
    # Load calibration (non-fatal if missing)
    cal_mgr = CalibrationManager()
    try:
        profile = cal_mgr.load(args.arm_id)
        logger.info(
            "Loaded calibration for '%s': %d joints, %d inversions",
            args.arm_id,
            len(profile.zeros),
            sum(1 for v in profile.inversions.values() if v),
        )
    except Exception:
        logger.warning(
            "No calibration profile found for '%s' -- proceeding without calibration",
            args.arm_id,
        )

    robot = _get_robot(args)
    library = PrimitiveLibrary()
    results: list[dict] = []

    for step in VALIDATION_STEPS:
        step_name = step["name"]
        primitive = step["primitive"]
        params = step["params"]

        logger.info("--- Running: %s (primitive=%s) ---", step_name, primitive)

        try:
            result = await library.run(primitive, robot, params)
        except Exception as exc:
            logger.error("Primitive '%s' raised exception: %s", step_name, exc)
            result = PrimitiveResult(
                success=False,
                error_message=str(exc),
            )

        summary = _format_result(step_name, result)
        results.append(summary)

        status = "PASS" if result.success else "FAIL"
        logger.info(
            "  %s | duration=%.1fms | force=%.4f | error=%s",
            status,
            result.duration_ms,
            result.actual_force,
            result.error_message or "none",
        )

    # Disconnect mock robot if applicable
    if hasattr(robot, "disconnect"):
        robot.disconnect()

    # Write summary
    output_path = _write_summary(args.arm_id, results)
    overall_pass = all(r["success"] for r in results)

    logger.info("---")
    logger.info("Overall: %s", "PASS" if overall_pass else "FAIL")
    logger.info("Summary written to: %s", output_path)

    return overall_pass


# ---------------------------------------------------------------------------
# Check-only mode: validate connectivity without running primitives
# ---------------------------------------------------------------------------


def _run_check_only() -> bool:
    """Check connectivity for all configured arms.

    Loads the config, lists configured arms, checks port availability,
    attempts to connect each arm, and reads joint positions.

    Returns:
        True if all enabled arms connected successfully.
    """
    from nextis.config import load_config
    from nextis.hardware.arm_registry import ArmRegistryService

    # 1. Check lerobot availability
    try:
        import lerobot  # noqa: F401

        logger.info("[OK] lerobot available (from %s)", lerobot.__file__)
    except ImportError:
        logger.error("[FAIL] lerobot not importable — check PYTHONPATH")
        return False

    # 2. Load config
    config = load_config()
    arms_cfg = config.get("arms", {})
    pairings_cfg = config.get("pairings", [])

    if not arms_cfg:
        logger.warning("No arms configured in settings.yaml")
        return True

    logger.info("Found %d arm(s), %d pairing(s)", len(arms_cfg), len(pairings_cfg))

    # 3. Check CAN bus (if any Damiao arms)
    damiao_ports = {
        v.get("port", "can0")
        for v in arms_cfg.values()
        if v.get("motor_type") == "damiao"
    }
    for port in damiao_ports:
        can_state_path = f"/sys/class/net/{port}/operstate"
        try:
            with open(can_state_path) as f:
                state = f.read().strip()
            if state in ("up", "unknown"):
                logger.info("[OK] CAN interface %s is %s", port, state)
            else:
                logger.error(
                    "[FAIL] CAN interface %s is %s — run: sudo bash scripts/setup_can.sh %s",
                    port, state, port,
                )
        except FileNotFoundError:
            logger.error(
                "[FAIL] CAN interface %s not found — run: sudo bash scripts/setup_can.sh %s",
                port, port,
            )

    # 4. Check serial ports (Dynamixel/Feetech)
    serial_ports = {
        v.get("port", "")
        for v in arms_cfg.values()
        if v.get("motor_type") in ("dynamixel_xl330", "dynamixel_xl430", "sts3215")
    }
    for port in serial_ports:
        if not port:
            continue
        if Path(port).exists():
            logger.info("[OK] Serial port %s exists", port)
        else:
            logger.error("[FAIL] Serial port %s not found — check USB connection", port)

    # 5. Attempt to connect each enabled arm
    registry = ArmRegistryService()
    all_ok = True

    for arm_id, arm_cfg in arms_cfg.items():
        if not arm_cfg.get("enabled", True):
            logger.info("[SKIP] %s (disabled)", arm_id)
            continue

        arm = registry.get_arm(arm_id)
        if arm is None:
            logger.error("[FAIL] %s not in registry", arm_id)
            all_ok = False
            continue

        try:
            result = registry.connect_arm(arm_id)
            if result.get("success"):
                logger.info(
                    "[OK] %s connected (%s on %s)",
                    arm_id, arm_cfg.get("motor_type"), arm_cfg.get("port"),
                )
            else:
                logger.error("[FAIL] %s: %s", arm_id, result.get("error", "unknown"))
                all_ok = False
                continue
        except Exception as e:
            logger.error("[FAIL] %s: %s", arm_id, e)
            all_ok = False
            continue

        # 6. Read joint positions
        instance = registry.get_arm_instance(arm_id)
        if instance is not None and hasattr(instance, "get_observation"):
            try:
                obs = instance.get_observation()
                positions = {k: round(v, 3) for k, v in obs.items() if ".pos" in k}
                logger.info("  Joints: %s", positions)
            except Exception as e:
                logger.warning("  Could not read joints: %s", e)

    # 7. Disconnect all
    for arm_id in list(registry.arm_instances.keys()):
        with contextlib.suppress(Exception):
            registry.disconnect_arm(arm_id)

    logger.info("---")
    logger.info("Overall: %s", "PASS" if all_ok else "FAIL")
    return all_ok


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments and run the validation sequence."""
    parser = argparse.ArgumentParser(
        description="Validate hardware by exercising motion primitives.",
    )
    parser.add_argument(
        "--arm-id",
        required=True,
        help="Arm identifier (must match registry or calibration profile).",
    )
    parser.add_argument(
        "--port",
        default="can0",
        help="CAN interface or serial port (default: can0).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use MockRobot instead of real hardware.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check connectivity for all configured arms without running primitives.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    passed = _run_check_only() if args.check_only else asyncio.run(_run_validation(args))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
