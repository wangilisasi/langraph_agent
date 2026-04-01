# Implementation Progress

> Last updated: March 26, 2026

## What Was Built

We converted the existing LangGraph research assistant into an **HTTP injection attack detection and response agent** for PhD research. The system uses a **tiered pipeline**: a fast ML model handles clear-cut cases inline (milliseconds), and an LLM agent analyzes uncertain requests asynchronously (seconds) without blocking user traffic.

## Files Created

| File | Purpose |
|------|---------|
| `database.py` | SQLite layer — `incidents` and `ip_reputation` tables, all CRUD operations |
| `detector.py` | ML model wrapper — loads model, runs inference, returns confidence score. Contains the `detector_node` (graph node) and `route_by_confidence` (3-way routing function). **Has a placeholder model — swap in your real one here.** |
| `response_nodes.py` | Two fast-path nodes: `auto_respond` (block + ban for high-confidence attacks) and `pass_through` (log-only for benign). Neither uses the LLM. |
| `security_tools.py` | Five LangChain tools the LLM uses in the grey zone: `inspect_request_fields`, `check_ip_history`, `log_security_incident`, `block_ip`, `send_alert` |
| `security_agent.py` | The full LangGraph security pipeline — wires detector → 3-way routing → response nodes / LLM analysis loop. Defines `SecurityState` and the security system prompt. |
| `server.py` | FastAPI server with `/analyze`, `/ip/{ip}`, `/incidents`, `/stats` endpoints. Grey-zone requests return immediately and are analyzed by the LLM in a background thread. |
| `ARCHITECTURE.md` | Full design document — scope, architecture diagrams, state schema, DB schema, config, implementation plan |

## Files NOT Modified

| File | Status |
|------|--------|
| `agent.py` | Untouched — still the original research assistant agent |
| `tools.py` | Untouched — original research tools (web search, file ops, etc.) |
| `main.py` | Untouched — original CLI chat loop |

## How the Pipeline Works

```
HTTP Request → detector (your ML model, ~ms)
                │
                ├── confidence >= 0.95 → auto_respond (block + log, no LLM)
                │
                ├── 0.15 < confidence < 0.95 → LLM agent analyzes async
                │     └── inspect fields → check IP history → decide → log/block/alert
                │
                └── confidence <= 0.15 → pass_through (log only, no LLM)
```

## How to Run

```powershell
# Activate venv
.venv\Scripts\Activate.ps1

# Start the API server
python -m uvicorn server:app --port 8000

# Swagger docs at http://127.0.0.1:8000/docs
```

### Test with curl / httpx

```powershell
# Benign request
Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/analyze `
  -ContentType "application/json" `
  -Body '{"method":"GET","url":"/api/products","source_ip":"10.0.0.1"}'

# Suspicious request (grey zone with placeholder model)
Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/analyze `
  -ContentType "application/json" `
  -Body '{"method":"POST","url":"/api/search","body":"q=select * from users","source_ip":"10.0.0.99"}'

# Check stats
Invoke-RestMethod -Uri http://127.0.0.1:8000/stats

# Check IP reputation
Invoke-RestMethod -Uri http://127.0.0.1:8000/ip/10.0.0.99
```

## Where to Plug In Your Real Model

Open `detector.py` and modify two functions:

### 1. `load_model()` — load your trained model

```python
def load_model(path: str | None = None) -> None:
    global _model
    import joblib  # or torch, tensorflow, etc.
    _model = joblib.load(path or "models/injection_clf.pkl")
```

### 2. `predict()` — run inference

```python
def predict(http_request: dict) -> float:
    features = your_feature_extractor(http_request)
    prob = _model.predict_proba(features)[0][1]
    return float(prob)
```

The rest of the pipeline (routing, response, LLM analysis, database) works automatically once these two functions return a valid 0.0–1.0 probability.

## Configuration (detector.py)

| Variable | Default | What it controls |
|----------|---------|------------------|
| `HIGH_THRESHOLD` | 0.95 | Above this → auto-block, no LLM |
| `LOW_THRESHOLD` | 0.15 | Below this → benign pass-through |

## Configuration (response_nodes.py)

| Variable | Default | What it controls |
|----------|---------|------------------|
| `TEMP_BAN_DURATION_MINUTES` | 30 | How long a temp IP ban lasts |
| `REPEAT_OFFENDER_THRESHOLD` | 3 | Attacks before auto-escalation to temp ban |
| `REPEAT_OFFENDER_WINDOW_MINUTES` | 60 | Time window for counting repeat offenses |

## Database

SQLite at `output/security.db` (auto-created on first run).

**Tables:**
- `incidents` — every analyzed request (timestamp, IP, confidence, decision, action, LLM reasoning)
- `ip_reputation` — per-IP tracking (request count, attack count, grey-zone flags, ban status)

## What's Left — TODO

### Phase 5: Batch Evaluation + Metrics Collection (PENDING)

- Batch-mode script that feeds a dataset of labeled HTTP requests through the pipeline
- Computes: accuracy per tier, escalation rate, latency, false positive rate, false negative rate
- Exports incident data from SQLite to CSV for analysis in pandas/R
- This is the research evaluation piece for the thesis

## Commit History (this session)

1. `Add architecture plan for HTTP injection detection and response agent`
2. `Add database module with incidents and IP reputation tables`
3. `Add detector module with ML model interface, confidence routing, and graph node`
4. `Add auto_respond and pass_through response nodes with repeat offender escalation`
5. `Add security tools for LLM grey-zone analysis (inspect, history, log, block, alert)`
6. `Wire full security graph with 3-way routing and LLM grey-zone analysis`
7. `Add FastAPI server with /analyze endpoint and async LLM grey-zone processing`
