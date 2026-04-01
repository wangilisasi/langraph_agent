"""FastAPI server for the HTTP injection detection and response pipeline."""

import asyncio
import logging
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel, Field

from detector import (
    parse_http_request,
    predict,
    load_model,
    HIGH_THRESHOLD,
    LOW_THRESHOLD,
)
from response_nodes import auto_respond, pass_through
from security_agent import security_agent
import database as db

logger = logging.getLogger("security_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Thread pool for running the synchronous LangGraph agent in the background
_executor = ThreadPoolExecutor(max_workers=4)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    load_model()
    db.init_db()
    logger.info(
        "Security server started (HIGH=%.2f, LOW=%.2f)",
        HIGH_THRESHOLD, LOW_THRESHOLD,
    )
    yield
    _executor.shutdown(wait=False)
    logger.info("Security server stopped")


app = FastAPI(
    title="HTTP Injection Detection API",
    description="Tiered detection pipeline: fast ML model inline, LLM for grey-zone requests.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    method: str = Field(default="GET", examples=["GET", "POST", "PUT"])
    url: str = Field(examples=["/api/login"])
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = Field(default="")
    source_ip: str = Field(examples=["192.168.1.100"])


class AnalyzeResponse(BaseModel):
    request_id: str
    confidence: float
    tier: str
    decision: str
    action_taken: str
    detail: str


# ---------------------------------------------------------------------------
# Grey-zone background processing
# ---------------------------------------------------------------------------

def _run_llm_analysis(http_request: dict, detection_result: dict) -> None:
    """Run the full LangGraph security agent for a grey-zone request.

    This runs synchronously in a thread pool — does not block the API response.
    """
    request_id = detection_result["request_id"]
    try:
        logger.info("LLM analysis started for %s", request_id)
        security_agent.invoke({
            "http_request": http_request,
            "detection_result": detection_result,
        })
        logger.info("LLM analysis completed for %s", request_id)
    except Exception:
        logger.exception("LLM analysis failed for %s", request_id)


async def queue_llm_analysis(http_request: dict, detection_result: dict) -> None:
    """Submit a grey-zone request to the thread pool for async LLM analysis."""
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_llm_analysis, http_request, detection_result)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    """Analyze an HTTP request for injection attacks.

    - High confidence attack: blocked immediately (inline, milliseconds)
    - Benign: passed through (inline, milliseconds)
    - Grey zone: passed through now, queued for async LLM analysis
    """
    if db.is_ip_banned(req.source_ip):
        http_request = parse_http_request(
            method=req.method, url=req.url,
            headers=req.headers, body=req.body, source_ip=req.source_ip,
        )
        return AnalyzeResponse(
            request_id=http_request["request_id"],
            confidence=1.0,
            tier="banned",
            decision="attack",
            action_taken="block",
            detail=f"IP {req.source_ip} is currently banned.",
        )

    http_request = parse_http_request(
        method=req.method, url=req.url,
        headers=req.headers, body=req.body, source_ip=req.source_ip,
    )

    confidence = predict(http_request)
    request_id = http_request["request_id"]

    if confidence >= HIGH_THRESHOLD:
        detection_result = {
            "request_id": request_id,
            "confidence": round(confidence, 4),
            "is_attack": True,
            "is_grey_zone": False,
            "tier": "high",
        }
        state = {"http_request": http_request, "detection_result": detection_result}
        result = auto_respond(state)
        resp = result["response"]
        return AnalyzeResponse(
            request_id=request_id,
            confidence=resp["confidence"],
            tier="high",
            decision=resp["decision"],
            action_taken=resp["action_taken"],
            detail=resp["detail"],
        )

    if confidence <= LOW_THRESHOLD:
        detection_result = {
            "request_id": request_id,
            "confidence": round(confidence, 4),
            "is_attack": False,
            "is_grey_zone": False,
            "tier": "low",
        }
        state = {"http_request": http_request, "detection_result": detection_result}
        result = pass_through(state)
        resp = result["response"]
        return AnalyzeResponse(
            request_id=request_id,
            confidence=resp["confidence"],
            tier="low",
            decision=resp["decision"],
            action_taken=resp["action_taken"],
            detail=resp["detail"],
        )

    # Grey zone — pass through immediately, analyze in background
    detection_result = {
        "request_id": request_id,
        "confidence": round(confidence, 4),
        "is_attack": False,
        "is_grey_zone": True,
        "tier": "grey",
    }

    db.update_ip_after_request(
        source_ip=req.source_ip,
        is_attack=False,
        is_grey_zone=True,
    )

    await queue_llm_analysis(http_request, detection_result)

    return AnalyzeResponse(
        request_id=request_id,
        confidence=round(confidence, 4),
        tier="grey",
        decision="pending",
        action_taken="under_review",
        detail=(
            f"Request from {req.source_ip} is in the grey zone "
            f"(confidence {confidence:.2f}). Passed through; "
            f"queued for LLM analysis."
        ),
    )


@app.get("/ip/{source_ip}")
async def get_ip_info(source_ip: str):
    """Get reputation and recent incidents for a source IP."""
    reputation = db.get_ip_reputation(source_ip)
    incidents = db.get_recent_incidents(source_ip, limit=20)
    return {
        "source_ip": source_ip,
        "reputation": reputation,
        "recent_incidents": incidents,
        "is_banned": db.is_ip_banned(source_ip),
    }


@app.get("/incidents")
async def get_incidents(source_ip: str | None = None, limit: int = 50):
    """List recent incidents, optionally filtered by IP."""
    if source_ip:
        return db.get_recent_incidents(source_ip, limit=limit)

    conn = db._get_connection()
    rows = conn.execute(
        """
        SELECT request_id, timestamp, source_ip, confidence,
               decision, decision_source, action_taken
        FROM incidents
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


@app.get("/stats")
async def get_stats():
    """Get aggregate detection statistics."""
    stats = db.get_incident_stats()
    stats["thresholds"] = {
        "high": HIGH_THRESHOLD,
        "low": LOW_THRESHOLD,
    }
    return stats
