"""Non-LLM response nodes for the high-confidence and benign paths."""

import datetime

from detector import HIGH_THRESHOLD

import database as db

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TEMP_BAN_DURATION_MINUTES = 30
REPEAT_OFFENDER_THRESHOLD = 3       # grey-zone flags before auto-escalation
REPEAT_OFFENDER_WINDOW_MINUTES = 60


# ---------------------------------------------------------------------------
# auto_respond node — high-confidence attack, no LLM needed
# ---------------------------------------------------------------------------

def auto_respond(state: dict) -> dict:
    """Handle a high-confidence attack: block, ban, log, and optionally alert.

    This path runs in milliseconds — no LLM call.
    """
    http_req = state["http_request"]
    detection = state["detection_result"]
    source_ip = http_req["source_ip"]

    action = "block"

    ip_rep = db.update_ip_after_request(
        source_ip=source_ip,
        is_attack=True,
        is_grey_zone=False,
    )

    if ip_rep["attack_count"] >= REPEAT_OFFENDER_THRESHOLD:
        ban_until = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(minutes=TEMP_BAN_DURATION_MINUTES)
        ).isoformat()
        db.set_ip_ban(source_ip, "temp_ban", ban_until)
        action = "temp_ban"

    incident = db.log_incident(
        request_id=detection["request_id"],
        source_ip=source_ip,
        confidence=detection["confidence"],
        decision="attack",
        decision_source="model",
        action_taken=action,
        method=http_req.get("method"),
        url=http_req.get("url"),
        headers=http_req.get("headers"),
        body=http_req.get("body"),
    )

    return {
        "response": {
            "request_id": detection["request_id"],
            "decision": "attack",
            "confidence": detection["confidence"],
            "action_taken": action,
            "source": "model",
            "detail": f"Blocked request from {source_ip} (confidence {detection['confidence']}). "
                      + (f"IP temp-banned for {TEMP_BAN_DURATION_MINUTES} min (repeat offender)."
                         if action == "temp_ban"
                         else "Request blocked."),
        },
        "incident_log": [incident],
    }


# ---------------------------------------------------------------------------
# pass_through node — benign request, just log it
# ---------------------------------------------------------------------------

def pass_through(state: dict) -> dict:
    """Handle a low-confidence (benign) request: log and let it pass.

    This path runs in milliseconds — no LLM call.
    """
    http_req = state["http_request"]
    detection = state["detection_result"]
    source_ip = http_req["source_ip"]

    db.update_ip_after_request(
        source_ip=source_ip,
        is_attack=False,
        is_grey_zone=False,
    )

    incident = db.log_incident(
        request_id=detection["request_id"],
        source_ip=source_ip,
        confidence=detection["confidence"],
        decision="benign",
        decision_source="model",
        action_taken="log_only",
        method=http_req.get("method"),
        url=http_req.get("url"),
        headers=http_req.get("headers"),
        body=http_req.get("body"),
    )

    return {
        "response": {
            "request_id": detection["request_id"],
            "decision": "benign",
            "confidence": detection["confidence"],
            "action_taken": "log_only",
            "source": "model",
            "detail": f"Request from {source_ip} classified as benign (confidence {detection['confidence']}).",
        },
        "incident_log": [incident],
    }
