"""LangGraph agent built with explicit Nodes and Edges."""

import atexit
from typing import Annotated
from typing_extensions import TypedDict

from dotenv import load_dotenv

load_dotenv()

import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import AnyMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from tools import (
    web_search,
    web_search_deep,
    fetch_page,
    get_current_datetime,
    save_to_file,
    read_file,
    list_saved_files,
    quick_answer,
)

# ── State ────────────────────────────────────────────────────────────────
# This TypedDict defines the data that flows through every node.
# `add_messages` is a reducer that appends new messages instead of replacing.


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


# ── Model ────────────────────────────────────────────────────────────────
# OpenRouter is OpenAI-compatible, so we reuse ChatOpenAI with a different
# base_url and api_key. You can swap the model to any on OpenRouter:
# https://openrouter.ai/models
tools = [
    web_search,
    web_search_deep,
    fetch_page,
    get_current_datetime,
    save_to_file,
    read_file,
    list_saved_files,
    quick_answer,
]

llm = ChatOpenAI(
    model="openai/gpt-5-nano",                   # OpenRouter model ID
    base_url="https://openrouter.ai/api/v1",     # point to OpenRouter
    api_key=os.getenv("OPENROUTER_API_KEY"),      # use the OpenRouter key
    temperature=0,
    max_retries=2,                               # Handle temporary network failures
    timeout=30.0,                                # Don't hang forever
)
llm_with_tools = llm.bind_tools(tools)

SYSTEM_PROMPT = SystemMessage(
    content=(
        "You are a research assistant. Your job is to help users find, "
        "analyse, and organise information from the web.\n\n"
        "Guidelines:\n"
        "- Use web_search for general queries, web_search_deep when you need detailed content.\n"
        "- Use quick_answer for simple factual questions.\n"
        "- Use fetch_page when the user gives you a specific URL.\n"
        "- Save important findings with save_to_file so the user can reference them later.\n"
        "- Always cite your sources with URLs.\n"
        "- Be concise but thorough."
    )
)


# ── Nodes ────────────────────────────────────────────────────────────────
# Each node is a function that receives the current state and returns
# a partial state update (here, new messages to append).


def chatbot(state: AgentState) -> AgentState:
    """Call the LLM. It may decide to invoke tools or reply directly."""
    messages = [SYSTEM_PROMPT] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


# ToolNode automatically executes whichever tool the LLM requested.
tool_node = ToolNode(tools=tools)


# ── Conditional edge ────────────────────────────────────────────────────
# After the chatbot node we need to decide: did the LLM call a tool,
# or did it produce a final answer?


def should_continue(state: AgentState) -> str:
    """Route to 'tools' if the last message has tool calls, else 'end'."""
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END


# ── Build the graph ─────────────────────────────────────────────────────
graph = StateGraph(AgentState)

# 1. Add nodes
graph.add_node("chatbot", chatbot)
graph.add_node("tools", tool_node)

# 2. Add edges
graph.add_edge(START, "chatbot")              # entry point
graph.add_conditional_edges("chatbot", should_continue)  # chatbot → tools | END
graph.add_edge("tools", "chatbot")            # after tools, loop back to chatbot

# 3. Compile into a runnable
CHECKPOINT_DB_PATH = os.getenv("CHECKPOINT_DB_PATH", "output/agent_checkpoints.db")
_checkpointer_cm = SqliteSaver.from_conn_string(CHECKPOINT_DB_PATH)
checkpointer = _checkpointer_cm.__enter__()


def _close_checkpointer() -> None:
    _checkpointer_cm.__exit__(None, None, None)


atexit.register(_close_checkpointer)
agent = graph.compile(checkpointer=checkpointer)
