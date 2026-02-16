"""Basic tools the agent can use."""

import datetime
import math
from langchain_core.tools import tool


@tool
def get_current_time() -> str:
    """Return the current date and time."""
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


@tool
def calculator(expression: str) -> str:
    """Evaluate a math expression. Supports basic arithmetic and common math functions.

    Args:
        expression: A math expression like '2 + 2' or 'sqrt(16) * 3'.
    """
    allowed_names = {
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "pi": math.pi,
        "e": math.e,
        "abs": abs,
        "round": round,
        "pow": pow,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"Error evaluating expression: {e}"


@tool
def search_notes(query: str) -> str:
    """Search through saved notes/knowledge base (stub – replace with real logic).

    Args:
        query: The search query.
    """
    # Placeholder – swap this for a vector-store lookup, file search, etc.
    notes = {
        "langgraph": "LangGraph is a library for building stateful, multi-actor applications with LLMs.",
        "agents": "Agents use an LLM to decide which actions to take and in what order.",
        "tools": "Tools are functions that an agent can call to interact with the outside world.",
    }
    results = [v for k, v in notes.items() if query.lower() in k.lower()]
    return "\n".join(results) if results else "No matching notes found."
