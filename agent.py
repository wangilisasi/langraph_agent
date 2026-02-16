"""LangGraph agent built with explicit Nodes and Edges."""

from typing import Annotated
from typing_extensions import TypedDict

from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.messages import AnyMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from tools import get_current_time, calculator, search_notes, word_counter

# ── State ────────────────────────────────────────────────────────────────
# This TypedDict defines the data that flows through every node.
# `add_messages` is a reducer that appends new messages instead of replacing.


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


# ── Model ────────────────────────────────────────────────────────────────
tools = [get_current_time, calculator, search_notes, word_counter]
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
llm_with_tools = llm.bind_tools(tools)          # let the LLM know about tools

SYSTEM_PROMPT = SystemMessage(
    content=(
        "You are a helpful assistant. "
        "Use the available tools when they can help answer the user's question. "
        "Always explain your reasoning briefly before giving a final answer."
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
agent = graph.compile()
