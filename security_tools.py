"""LangChain tools for the LLM agent to use when analyzing grey-zone requests."""

import datetime
import json
from pathlib import Path

from langchain_core.tools import tool

import database as db

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


@tool
def inspect_request_fields(request_json: str) -> str:
    """Decompose an HTTP request into its individual fields for targeted analysis.

    Use this to examine specific parts of a suspicious request (URL params,
    headers, body) and look for injection patterns.

    Args:
        request_json: JSON string of the HTTP request dict.
    """
    try:
        req = json.loads(request_json)
    except json.JSONDecodeError:
        return "Error: invalid JSON. Pass the http_request dict as a JSON string."

    sections = []

    sections.append(f"Method: {req.get('method', 'N/A')}")
    sections.append(f"URL: {req.get('url', 'N/A')}")
    sections.append(f"Source IP: {req.get('source_ip', 'N/A')}")

    headers = req.get("headers", {})
    if headers:
        header_lines = [f"  {k}: {v}" for k, v in headers.items()]
        sections.append("Headers:\n" + "\n".join(header_lines))
    else:
        sections.append("Headers: (none)")

    body = req.get("body", "")
    if body:
        sections.append(f"Body ({len(body)} chars):\n  {body[:2000]}")
    else:
        sections.append("Body: (empty)")

    url = req.get("url", "")
    if "?" in url:
        query_string = url.split("?", 1)[1]
        params = query_string.split("&")
        param_lines = [f"  {p}" for p in params]
        sections.append("Query Parameters:\n" + "\n".join(param_lines))

    return "\n\n".join(sections)


@tool
def check_ip_history(source_ip: str) -> str:
    """Look up the reputation and recent incident history for a source IP.

    Use this to see if the IP has been flagged before, how many requests
    it has sent, and what actions were taken.

    Args:
        source_ip: The IP address to look up.
    """
    rep = db.get_ip_reputation(source_ip)
    if rep is None:
        return f"No history found for IP {source_ip}. This is a first-time visitor."

    lines = [
        f"IP: {source_ip}",
        f"First seen: {rep['first_seen']}",
        f"Last seen: {rep['last_seen']}",
        f"Total requests: {rep['total_requests']}",
        f"Confirmed attacks: {rep['attack_count']}",
        f"Grey-zone flags: {rep['grey_zone_count']}",
        f"Escalation level: {rep['escalation_level']}",
        f"Ban until: {rep['ban_until'] or 'N/A'}",
    ]

    recent = db.get_recent_incidents(source_ip, limit=5)
    if recent:
        lines.append("\nRecent incidents:")
        for inc in recent:
            lines.append(
                f"  [{inc['timestamp']}] conf={inc['confidence']:.2f} "
                f"decision={inc['decision']} by={inc['decision_source']} "
                f"action={inc['action_taken']}"
            )

    return "\n".join(lines)


@tool
def log_security_incident(
    request_id: str,
    source_ip: str,
    confidence: float,
    decision: str,
    action_taken: str,
    reasoning: str,
    method: str = "",
    url: str = "",
) -> str:
    """Log the LLM's analysis decision for a grey-zone request.

    Call this after you have analyzed a request and decided whether it is
    an attack or benign. This writes to the incident database.

    Args:
        request_id: The unique request ID from the detection result.
        source_ip: Source IP address of the request.
        confidence: The original ML model confidence score.
        decision: Your verdict — must be 'attack' or 'benign'.
        action_taken: Action to take — 'log_only', 'block', 'temp_ban', or 'alert'.
        reasoning: Your explanation of why you made this decision.
        method: HTTP method (GET, POST, etc.).
        url: The request URL.
    """
    if decision not in ("attack", "benign"):
        return "Error: decision must be 'attack' or 'benign'."
    if action_taken not in ("log_only", "block", "temp_ban", "alert"):
        return "Error: action_taken must be one of: log_only, block, temp_ban, alert."

    is_attack = decision == "attack"

    db.update_ip_after_request(
        source_ip=source_ip,
        is_attack=is_attack,
        is_grey_zone=True,
    )

    incident = db.log_incident(
        request_id=request_id,
        source_ip=source_ip,
        confidence=confidence,
        decision=decision,
        decision_source="llm",
        action_taken=action_taken,
        method=method or None,
        url=url or None,
        llm_reasoning=reasoning,
    )

    return f"Incident logged: {decision} / {action_taken} for request {request_id}."


@tool
def block_ip(source_ip: str, duration_minutes: int = 30) -> str:
    """Temporarily ban an IP address for a specified duration.

    Use this when you determine a request is malicious and want to prevent
    future requests from this IP.

    Args:
        source_ip: The IP address to ban.
        duration_minutes: How long the ban lasts (default 30 minutes).
    """
    rep = db.get_ip_reputation(source_ip)
    if rep is None:
        return f"Error: IP {source_ip} has no reputation record. Log an incident first."

    ban_until = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=duration_minutes)
    ).isoformat()

    db.set_ip_ban(source_ip, "temp_ban", ban_until)
    return f"IP {source_ip} temporarily banned until {ban_until} ({duration_minutes} min)."


@tool
def send_alert(source_ip: str, summary: str, severity: str = "medium") -> str:
    """Send a security alert about a suspicious or confirmed attack.

    This logs the alert to a file. In production, this would send to
    Slack, email, or a SIEM system.

    Args:
        source_ip: The IP address involved.
        summary: Brief description of what was detected.
        severity: Alert severity — 'low', 'medium', 'high', or 'critical'.
    """
    if severity not in ("low", "medium", "high", "critical"):
        return "Error: severity must be one of: low, medium, high, critical."

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    alert_entry = (
        f"[{timestamp}] ALERT [{severity.upper()}] IP={source_ip}\n"
        f"  {summary}\n\n"
    )

    alert_file = OUTPUT_DIR / "security_alerts.log"
    with open(alert_file, "a", encoding="utf-8") as f:
        f.write(alert_entry)

    return f"Alert sent: [{severity.upper()}] {summary}"


# Collect all security tools for easy import
security_tools = [
    inspect_request_fields,
    check_ip_history,
    log_security_incident,
    block_ip,
    send_alert,
]
