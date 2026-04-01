"""LangGraph security agent — HTTP injection detection and response pipeline."""

import json
import operator
import os
from typing import Annotated, TypedDict

from dotenv import load_dotenv

load_dotenv()

from pydantic import SecretStr
from langchain_openai import ChatOpenAI
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from detector import detector_node, route_by_confidence
from response_nodes import auto_respond, pass_through
from security_tools import security_tools


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class SecurityState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    http_request: dict
    detection_result: dict
    response: dict
    incident_log: Annotated[list[dict], operator.add]


# ---------------------------------------------------------------------------
# LLM setup (reuses the same OpenRouter config)
# ---------------------------------------------------------------------------

openrouter_api_key = os.getenv("OPENROUTER_API_KEY")

llm = ChatOpenAI(
    model="openai/gpt-5-nano",
    base_url="https://openrouter.ai/api/v1",
    api_key=SecretStr(openrouter_api_key) if openrouter_api_key else None,
    temperature=0,
    max_retries=2,
    timeout=30.0,
)

llm_with_security_tools = llm.bind_tools(security_tools)


# ---------------------------------------------------------------------------
# System prompt for grey-zone analysis
# ---------------------------------------------------------------------------

SECURITY_SYSTEM_PROMPT = SystemMessage(content="""\
You are a security analyst agent specializing in HTTP injection attack detection.

Your job: analyze an HTTP request that the ML model flagged as uncertain (grey zone)
and decide whether it is a genuine injection attack or a false positive.

## Injection types you look for
- SQL injection (SQLi): UNION, OR 1=1, DROP, SELECT, --, ;, etc.
- Cross-site scripting (XSS): <script>, onerror=, javascript:, etc.
- Command injection: |, ;, &&, $(), backticks, etc.
- LDAP injection: )(, *, |(, etc.
- Header injection: \\r\\n, %0d%0a in header values

## Your workflow
1. Use `inspect_request_fields` to examine the HTTP request in detail.
2. Use `check_ip_history` to see if this IP has been flagged before.
3. Analyze whether suspicious patterns are actual attacks or legitimate content.
4. Make your decision and call `log_security_incident` with your verdict and reasoning.
5. If it IS an attack, also call `block_ip` and optionally `send_alert`.

## Decision guidelines
- If the payload clearly contains injection syntax → decision: attack
- If the content looks legitimate but happens to contain keywords → decision: benign
- When in doubt, consider the IP history: repeat grey-zone flags are more suspicious
- Always provide clear reasoning — this is used for research evaluation

## Important
- You MUST call `log_security_incident` before finishing — every analysis must be recorded.
- Be precise and technical in your reasoning.
- Do not hallucinate patterns that are not in the actual request data.
""")


# ---------------------------------------------------------------------------
# Nodes for the LLM grey-zone path
# ---------------------------------------------------------------------------

def prepare_llm_context(state: SecurityState) -> SecurityState:
    """Convert the HTTP request + detection result into a message for the LLM."""
    http_req = state["http_request"]
    detection = state["detection_result"]

    context = (
        f"## HTTP Request to Analyze\n\n"
        f"**Request ID**: {detection['request_id']}\n"
        f"**ML Model Confidence**: {detection['confidence']} (grey zone)\n\n"
        f"**Method**: {http_req['method']}\n"
        f"**URL**: {http_req['url']}\n"
        f"**Source IP**: {http_req['source_ip']}\n"
        f"**Headers**: {json.dumps(http_req.get('headers', {}))}\n"
        f"**Body**: {http_req.get('body', '(empty)')}\n\n"
        f"Analyze this request for injection attacks. Use your tools to inspect "
        f"the fields, check IP history, then log your decision."
    )

    return {"messages": [HumanMessage(content=context)]}


def security_chatbot(state: SecurityState) -> SecurityState:
    """LLM node: analyze the grey-zone request using security tools."""
    messages = [SECURITY_SYSTEM_PROMPT] + state.get("messages", [])
    response = llm_with_security_tools.invoke(messages)
    return {"messages": [response]}


def should_continue_security(state: SecurityState) -> str:
    """Route to tools if the LLM made tool calls, otherwise end."""
    state_messages = state.get("messages", [])
    if not state_messages:
        return END
    last_message = state_messages[-1]
    if getattr(last_message, "tool_calls", None):
        return "security_tools"
    return END


security_tool_node = ToolNode(tools=security_tools)


# ---------------------------------------------------------------------------
# Build the security graph
# ---------------------------------------------------------------------------

graph = StateGraph(SecurityState)

# Add all nodes
graph.add_node("detector", detector_node)
graph.add_node("auto_respond", auto_respond)
graph.add_node("pass_through", pass_through)
graph.add_node("prepare_llm_context", prepare_llm_context)
graph.add_node("security_chatbot", security_chatbot)
graph.add_node("security_tools", security_tool_node)

# Entry point
graph.add_edge(START, "detector")

# 3-way routing based on confidence
graph.add_conditional_edges("detector", route_by_confidence, {
    "auto_respond": "auto_respond",
    "llm_analyze": "prepare_llm_context",
    "pass_through": "pass_through",
})

# Fast paths go straight to END
graph.add_edge("auto_respond", END)
graph.add_edge("pass_through", END)

# LLM grey-zone path: prepare context → chatbot ↔ tools → END
graph.add_edge("prepare_llm_context", "security_chatbot")
graph.add_conditional_edges("security_chatbot", should_continue_security)
graph.add_edge("security_tools", "security_chatbot")

# Compile
security_agent = graph.compile()
