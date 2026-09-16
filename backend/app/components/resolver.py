"""Pure, conservative module-to-board pin compatibility checks."""
from __future__ import annotations

from typing import Any

from app.components.models import ComponentPin, ComponentSpec


def _caps(pin, capability_type: str | None = None,
          role: str | None = None, rail: str | None = None):
    return [
        cap for cap in pin.capabilities
        if (capability_type is None or cap.type == capability_type)
        and (
            role is None
            or str(cap.role or "").casefold() == str(role).casefold()
        )
        and (rail is None or cap.rail == rail)
    ]


def _issue(code: str, severity: str, message: str, **extra: Any) -> dict:
    result = {"code": code, "severity": severity, "message": message}
    result.update(extra)
    return result


def _pin_matches_role(component_pin: ComponentPin, board_pin) -> tuple[bool, str | None]:
    role = component_pin.role.lower()
    required_role = component_pin.required_board_role
    required_caps = set(component_pin.required_capabilities)

    if required_caps and not any(cap.type in required_caps for cap in board_pin.capabilities):
        return False, f"requires capability {sorted(required_caps)}"
    if required_role and not any(
        str(cap.role or "").casefold() == required_role.casefold()
        for cap in board_pin.capabilities
    ):
        return False, f"requires board role {required_role!r}"

    if component_pin.required_rail:
        if not _caps(board_pin, "power", rail=component_pin.required_rail):
            return False, f"requires {component_pin.required_rail} power rail"
    elif role in {"ground", "gnd"} and not _caps(board_pin, "power", rail="gnd"):
        return False, "ground role must use a GND rail"
    elif role in {"vcc", "power"} and component_pin.voltage is not None:
        rail = "5v" if component_pin.voltage >= 4.5 else "3v3"
        if not _caps(board_pin, "power", rail=rail):
            return False, f"power role expects {rail} rail"

    # UART and I2C are directional from the module's perspective: module TX
    # connects to board RX, module RX to board TX; SDA/SCL must not swap.
    expected_role = required_role
    if role in {"uart_tx", "tx"}:
        expected_role = "rx"
    elif role in {"uart_rx", "rx"}:
        expected_role = "tx"
    elif role in {"i2c_sda", "sda"}:
        expected_role = "sda"
    elif role in {"i2c_scl", "scl"}:
        expected_role = "scl"
    if expected_role:
        matched = any(
            str(cap.role or "").casefold() == expected_role.casefold()
            for cap in board_pin.capabilities
        )
        if not matched:
            return False, f"module {role} requires board role {expected_role!r}"

    if role in {"pwm", "servo_signal", "led_anode"} and not _caps(board_pin, "pwm"):
        return False, "signal role requires PWM capability"
    if role in {"signal", "trig", "digital_output"} and not _caps(board_pin, "digital_io"):
        return False, "signal role requires digital_io capability"

    signal_voltage = component_pin.signal_voltage
    if signal_voltage is not None and board_pin.electrical is not None:
        board_voltage = board_pin.electrical.voltage
        tolerant = board_pin.electrical.five_volt_tolerant is True
        if signal_voltage > board_voltage + 0.25 and not tolerant:
            return False, f"{signal_voltage:g}V signal exceeds {board_voltage:g}V pin"
    return True, None


def resolve_assignment(profile, spec: ComponentSpec,
                       assignment: dict[str, str]) -> dict:
    issues: list[dict] = []
    roles: dict[str, dict] = {}
    board_ids = [pin_id for pin_id in assignment.values()]

    duplicates = sorted({pin_id for pin_id in board_ids if board_ids.count(pin_id) > 1})
    for pin_id in duplicates:
        issues.append(_issue("duplicate_board_pin", "danger",
                             f"multiple module pins are assigned to board pin {pin_id}",
                             board_pin=pin_id))

    for component_pin in spec.pins:
        board_id = assignment.get(component_pin.id)
        if board_id is None:
            if component_pin.required:
                issues.append(_issue("missing_required_pin", "warning",
                                     f"required module pin {component_pin.id} is not assigned",
                                     module_pin=component_pin.id))
            continue
        board_pin = profile.pin_by_id(board_id)
        if board_pin is None:
            issues.append(_issue("unknown_board_pin", "danger",
                                 f"board pin {board_id} does not exist",
                                 module_pin=component_pin.id, board_pin=board_id))
            roles[component_pin.id] = {"board_pin": board_id, "status": "invalid"}
            continue
        ok, reason = _pin_matches_role(component_pin, board_pin)
        status = "valid" if ok else "invalid"
        roles[component_pin.id] = {
            "board_pin": board_id,
            "status": status,
            "role": component_pin.role,
        }
        if not ok:
            code = "voltage_risk" if "signal exceeds" in (reason or "") else "capability_mismatch"
            severity = "danger" if code == "voltage_risk" else "warning"
            issues.append(_issue(code, severity,
                                 f"{component_pin.id} -> {board_id}: {reason}",
                                 module_pin=component_pin.id, board_pin=board_id))

    assigned_roles = {p.role.lower(): assignment.get(p.id) for p in spec.pins}
    if any(p.required and p.role.lower() in {"ground", "gnd"} and p.id in assignment
           for p in spec.pins) is False:
        issues.append(_issue("missing_common_ground", "danger",
                             "module has no assigned common ground"))

    # Make the common VCC/GND error explicit even when the generic rail rule
    # already caught it; it is much easier to render and explain to a user.
    for p in spec.pins:
        board_id = assignment.get(p.id)
        board_pin = profile.pin_by_id(board_id) if board_id else None
        if not board_pin:
            continue
        rails = {cap.rail for cap in board_pin.capabilities if cap.type == "power"}
        if p.role.lower() in {"vcc", "power"} and "gnd" in rails:
            issues.append(_issue("vcc_to_gnd", "danger",
                                 f"{p.id} (VCC) is assigned to GND pin {board_id}",
                                 module_pin=p.id, board_pin=board_id))
        if p.role.lower() in {"ground", "gnd"} and ("5v" in rails or "3v3" in rails):
            issues.append(_issue("gnd_to_power", "danger",
                                 f"{p.id} (GND) is assigned to power pin {board_id}",
                                 module_pin=p.id, board_pin=board_id))

    # Duplicate/role mismatch catches TX-TX, RX-RX and SDA/SCL swap errors.
    error_codes = {item["code"] for item in issues}
    if any(p.role.lower() in {"uart_tx", "uart_rx", "tx", "rx"}
           and p.id in assignment
           and roles.get(p.id, {}).get("status") == "invalid" for p in spec.pins):
        if "capability_mismatch" in error_codes:
            issues.append(_issue("uart_direction_mismatch", "danger",
                                 "UART TX/RX directions are crossed or connected to the same direction"))
    if any(p.role.lower() in {"i2c_sda", "i2c_scl", "sda", "scl"}
           and roles.get(p.id, {}).get("status") == "invalid" for p in spec.pins):
        issues.append(_issue("i2c_role_mismatch", "danger",
                             "I2C SDA/SCL roles are swapped or assigned to a non-I2C pin"))

    dangerous = any(issue["severity"] == "danger" for issue in issues)
    warnings = any(issue["severity"] == "warning" for issue in issues)
    status = "invalid" if dangerous else ("incomplete" if warnings else "valid")
    return {
        "ok": not dangerous and not warnings,
        "status": status,
        "board_id": profile.board.id,
        "component_spec": f"{spec.id}@{spec.version}",
        "pin_assignment": dict(assignment),
        "roles": roles,
        "issues": issues,
    }


def evaluate_observed_connections(profile, spec: ComponentSpec,
                                  assignment: dict[str, str],
                                  observations: list[dict]) -> dict:
    """Merge geometry/VLM connection candidates with the static rule result.

    Observations can only downgrade certainty; they never make an invalid
    electrical assignment valid.
    """
    plan = resolve_assignment(profile, spec, assignment)
    observed_by_role = {item.get("module_pin"): item for item in observations
                        if item.get("module_pin")}
    live_roles = {}
    for module_pin in spec.pins:
        expected = assignment.get(module_pin.id)
        observation = observed_by_role.get(module_pin.id)
        if observation is None:
            live_roles[module_pin.id] = {
                "expected_board_pin": expected,
                "status": "uncertain",
                "reason": "no geometric endpoint evidence",
            }
            continue
        actual = observation.get("board_pin")
        confidence = float(observation.get("confidence", 0.0) or 0.0)
        if observation.get("status") == "uncertain" or confidence < 0.5:
            status = "uncertain"
        elif actual == expected:
            status = "correct"
        else:
            status = "wrong_pin"
        live_roles[module_pin.id] = {
            "expected_board_pin": expected,
            "observed_board_pin": actual,
            "confidence": round(confidence, 3),
            "status": status,
        }
    plan["observed_roles"] = live_roles
    plan["ok"] = plan["ok"] and all(v["status"] == "correct" for v in live_roles.values())
    return plan
