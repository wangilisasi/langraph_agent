# HTTP Injection Attack Detection & Response Agent

## Overview

A LangGraph-based security agent that detects HTTP-layer injection attacks in real time and takes graduated response actions. The system uses a **hybrid inline/async architecture**: a fast ML model runs inline on every request (milliseconds), while an LLM agent handles uncertain cases asynchronously (seconds) without blocking user traffic.

## Scope

### In Scope

- SQL injection (SQLi)
- Cross-site scripting (XSS)
- Command injection (CMDi)
- LDAP injection
- XML/XPath injection
- Header injection
- Any injection delivered via HTTP request fields (URL, query params, headers, body)

### Out of Scope

- Non-HTTP attacks (SSH, DNS, TCP-level)
- DDoS / volumetric attacks
- Authentication/authorization flaws (unless delivered via injection)

## Architecture

### Tiered Detection Pipeline

```
HTTP Request arrives
│
▼
[INLINE — milliseconds]
detector_node (ML model)
│
├── confidence ≥ HIGH_THRESHOLD (0.95)
│     → BLOCK immediately
│     → Log incident
│     → Temporary IP ban
│     → Alert if repeat offender
│
├── LOW_THRESHOLD (0.15) < confidence < HIGH_THRESHOLD (0.95)
│     → PASS request through to origin (no user delay)
│     → Queue for async LLM analysis
│     → LLM analyzes → decides → updates IP reputation
│     → May ban IP for future requests
│
└── confidence ≤ LOW_THRESHOLD (0.15)
      → PASS through
      → Log only
```

### Why This Design

- **Speed**: 95%+ of requests never touch the LLM. The ML model handles clear-cut cases in milliseconds.
- **User experience**: Grey-zone requests pass through immediately — the LLM analyzes them after the fact. No user-facing latency for uncertain cases.
- **Accuracy**: Uncertain cases get LLM reasoning — contextual analysis, multi-field correlation, historical IP patterns.
- **Tunability**: The two thresholds (HIGH/LOW) are hyperparameters that control the precision/recall/latency tradeoff.

## Detection Model

- **Input**: Raw HTTP request (method, URL, headers, body)
- **Output**: Binary probability (0.0 = benign, 1.0 = attack)
- **Speed**: Milliseconds (runs inline in the request path)
- **Pre-trained**: Model is developed separately as part of the PhD research

## Graduated Response Actions

| Severity | Action | Reversible | When Used |
|----------|--------|------------|-----------|
| Low | Log incident | N/A | Every request (always) |
| Medium | Flag for review | N/A | Grey-zone requests queued for LLM |
| High | Block request | Yes | High-confidence attacks (inline) |
| High | Temporary IP ban | Yes | High-confidence or LLM-confirmed attacks |
| Critical | Permanent IP ban | Manual | Repeat offenders exceeding threshold |
| Critical | Alert admin | N/A | Critical or repeated attacks from same source |

## LLM Agent (Grey Zone Analysis)

The LLM agent is only invoked for requests where the ML model is uncertain. It provides:

1. **Contextual reasoning** — Distinguishes legitimate content containing attack-like patterns from actual attacks
2. **Multi-field correlation** — Checks if multiple HTTP fields contain suspicious patterns
3. **Historical reasoning** — Cross-references with past behavior from the same source IP
4. **Explainability** — Generates human-readable justification for the classification decision

### Agent Tools

| Tool | Purpose |
|------|---------|
| `inspect_request_fields` | Decompose HTTP request into parts for targeted analysis |
| `check_ip_history` | Query SQLite for past behavior from a source IP |
| `log_incident` | Write structured incident record to SQLite |
| `update_ip_reputation` | Escalate or de-escalate an IP's threat level |
| `block_ip` | Add IP to blocklist with a TTL |
| `send_alert` | Notify admin via webhook, file, or console |
| `search_attack_signatures` | RAG over OWASP/injection pattern knowledge base |

## State Schema

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    plan: str
    http_request: dict          # {method, url, headers, body, source_ip, timestamp}
    detection_result: dict      # {confidence, is_attack, request_id}
    incident_log: list[dict]    # accumulated incident records for this invocation
```

## Data Storage (SQLite)

### `incidents` table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| request_id | TEXT | Unique request identifier |
| timestamp | TEXT | ISO 8601 timestamp |
| source_ip | TEXT | Client IP address |
| method | TEXT | HTTP method |
| url | TEXT | Full request URL |
| headers | TEXT | JSON-serialized headers |
| body | TEXT | Request body |
| confidence | REAL | ML model confidence score |
| decision | TEXT | benign / attack |
| decision_source | TEXT | model / llm |
| action_taken | TEXT | log_only / block / temp_ban / perm_ban / alert |
| llm_reasoning | TEXT | LLM explanation (grey zone only, NULL otherwise) |

### `ip_reputation` table

| Column | Type | Description |
|--------|------|-------------|
| source_ip | TEXT PK | Client IP address |
| first_seen | TEXT | First request timestamp |
| last_seen | TEXT | Most recent request timestamp |
| total_requests | INTEGER | Total requests analyzed |
| attack_count | INTEGER | Confirmed attack count |
| grey_zone_count | INTEGER | Times flagged in grey zone |
| escalation_level | TEXT | none / monitored / temp_ban / perm_ban |
| ban_until | TEXT | Temp ban expiry (NULL if not banned) |

### Repeat Offender Logic

- Every request updates `ip_reputation`
- If an IP accumulates N grey-zone flags within a time window → auto-escalate to temporary ban
- The LLM agent sees full IP history and can escalate or de-escalate based on reasoning

## Entry Point

**FastAPI server** with a `/analyze` endpoint:

- Receives HTTP request metadata as JSON
- Inline path: ML model predicts → immediate response (block or pass)
- Async path: grey-zone requests queued → LangGraph agent processes in background
- Response to caller includes: `{decision, confidence, action_taken, request_id}`

## LangGraph Flow

```
START → detector
         │
         ├── "auto_respond"   → auto_respond_node → END
         ├── "llm_analyze"    → planner → chatbot ↔ tools → END
         └── "pass_through"   → log_only_node → END
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HIGH_THRESHOLD` | 0.95 | Above this → auto block |
| `LOW_THRESHOLD` | 0.15 | Below this → benign pass-through |
| `TEMP_BAN_DURATION_MINUTES` | 30 | Duration of temporary IP bans |
| `REPEAT_OFFENDER_THRESHOLD` | 3 | Grey-zone flags before auto-escalation |
| `REPEAT_OFFENDER_WINDOW_MINUTES` | 60 | Time window for counting repeat flags |

## Implementation Plan

### Phase 1: Foundation

1. Create SQLite schema (`incidents` + `ip_reputation` tables)
2. Build the detector node (loads ML model, classifies, writes to state)
3. Implement confidence-based routing (3-way conditional edge)

### Phase 2: Response Actions

4. Build `auto_respond` node (high-confidence path — block, ban, log, no LLM)
5. Build `log_only` node (benign path — log and pass through)
6. Implement response tools for the LLM agent (`check_ip_history`, `log_incident`, `update_ip_reputation`, `block_ip`, `send_alert`, `inspect_request_fields`, `search_attack_signatures`)

### Phase 3: Agent Integration

7. Update agent state schema with new fields
8. Wire the full graph (detector → routing → three paths)
9. Update system prompt for security-focused LLM reasoning

### Phase 4: API & Deployment

10. Build FastAPI server with `/analyze` endpoint
11. Implement async processing for grey-zone requests
12. Add repeat offender tracking logic

### Phase 5: Evaluation & Research

13. Add batch-mode entry point for running evaluation datasets
14. Build metrics collection (accuracy per tier, escalation rate, latency, false positive rate)
15. Export incident data for analysis (CSV/pandas from SQLite)
