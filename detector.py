"""HTTP injection attack detector — wraps your ML model for use as a graph node."""

import uuid
import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HIGH_THRESHOLD = 0.95   # Above this → auto-block, no LLM needed
LOW_THRESHOLD = 0.15    # Below this → benign, pass through

# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------
# Replace this section with your real model. The only contract is:
#   predict(http_request: dict) -> float   (0.0 = benign, 1.0 = attack)
#
# Example for a scikit-learn model:
#   import joblib
#   _model = joblib.load("models/injection_clf.pkl")
#
# Example for a PyTorch model:
#   import torch
#   _model = torch.load("models/injection_clf.pt")
#   _model.eval()

_model = None


def load_model(path: str | None = None) -> None:
    """Load the ML model into memory. Call once at startup.

    Replace the body of this function with your real model loading logic.
    """
    global _model
    # ------------------------------------------------------------------
    # TODO: Replace with your actual model loading code, e.g.:
    #   import joblib
    #   _model = joblib.load(path or "models/injection_clf.pkl")
    # ------------------------------------------------------------------
    _model = "placeholder"


def predict(http_request: dict) -> float:
    """Run the ML model on an HTTP request and return attack probability.

    Args:
        http_request: Dict with keys like method, url, headers, body.

    Returns:
        Float between 0.0 (benign) and 1.0 (attack).
    """
    if _model is None:
        raise RuntimeError("Model not loaded. Call load_model() first.")

    # ------------------------------------------------------------------
    # TODO: Replace with your actual inference code, e.g.:
    #
    #   features = extract_features(http_request)
    #   prob = _model.predict_proba(features)[0][1]
    #   return float(prob)
    #
    # For now, this returns a dummy value so the pipeline can be tested
    # end-to-end before you plug in the real model.
    # ------------------------------------------------------------------
    raw = f"{http_request.get('url', '')} {http_request.get('body', '')}"
    suspicious_patterns = ["select", "union", "<script", "' or ", "1=1", "drop table", "exec(", "${"]
    raw_lower = raw.lower()
    hits = sum(1 for p in suspicious_patterns if p in raw_lower)
    return min(hits * 0.3, 1.0)


# ---------------------------------------------------------------------------
# Helper: build a structured HTTP request dict
# ---------------------------------------------------------------------------

def parse_http_request(
    method: str = "GET",
    url: str = "/",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    source_ip: str = "0.0.0.0",
) -> dict[str, Any]:
    """Build the standard HTTP request dict used throughout the pipeline."""
    return {
        "request_id": str(uuid.uuid4()),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "method": method.upper(),
        "url": url,
        "headers": headers or {},
        "body": body or "",
        "source_ip": source_ip,
    }


# ---------------------------------------------------------------------------
# Graph node function
# ---------------------------------------------------------------------------

def detector_node(state: dict) -> dict:
    """LangGraph node: classify the HTTP request and write detection_result.

    Reads state["http_request"] and returns a partial state update with
    state["detection_result"] containing confidence and routing info.
    """
    http_request = state.get("http_request")
    if http_request is None:
        raise ValueError("detector_node requires state['http_request'] to be set.")

    confidence = predict(http_request)
    is_attack = confidence >= HIGH_THRESHOLD
    is_grey_zone = LOW_THRESHOLD < confidence < HIGH_THRESHOLD

    if confidence >= HIGH_THRESHOLD:
        tier = "high"
    elif confidence <= LOW_THRESHOLD:
        tier = "low"
    else:
        tier = "grey"

    return {
        "detection_result": {
            "request_id": http_request["request_id"],
            "confidence": round(confidence, 4),
            "is_attack": is_attack,
            "is_grey_zone": is_grey_zone,
            "tier": tier,
        }
    }


# ---------------------------------------------------------------------------
# Routing function for conditional edges
# ---------------------------------------------------------------------------

def route_by_confidence(state: dict) -> str:
    """Return the next node name based on detection confidence.

    Returns one of: "auto_respond", "llm_analyze", "pass_through"
    """
    result = state["detection_result"]
    tier = result["tier"]

    if tier == "high":
        return "auto_respond"
    elif tier == "grey":
        return "llm_analyze"
    else:
        return "pass_through"


# Auto-load the model on import so it's ready when the graph runs
load_model()
