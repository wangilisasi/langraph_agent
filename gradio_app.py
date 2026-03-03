"""Gradio UI for the LangGraph research agent."""

from __future__ import annotations

import uuid
from typing import Any

import gradio as gr

from agent import CHECKPOINT_DB_PATH, agent


def _extract_final_answer(result: dict[str, Any]) -> str:
    """Return the last AI message content."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "ai" and getattr(msg, "content", None):
            return str(msg.content)
    return "No response generated."


def _extract_tool_names(result: dict[str, Any]) -> list[str]:
    """Return tool names called in this turn."""
    names: list[str] = []
    messages = result.get("messages", [])

    for msg in messages:
        if getattr(msg, "type", None) == "ai" and getattr(msg, "tool_calls", None):
            for tool_call in msg.tool_calls:
                name = tool_call.get("name") if isinstance(tool_call, dict) else None
                if name:
                    names.append(name)
    return names


def _new_thread_id() -> str:
    return f"thread-{uuid.uuid4().hex[:8]}"


def _normalize_history(history: Any) -> list[dict[str, str]]:
    """Normalize legacy tuple history and message objects into dict messages."""
    if not history:
        return []

    normalized: list[dict[str, str]] = []
    for item in history:
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                normalized.append({"role": role, "content": content})
            continue

        if isinstance(item, (tuple, list)) and len(item) == 2:
            user_text, assistant_text = item
            if user_text is not None:
                normalized.append({"role": "user", "content": str(user_text)})
            if assistant_text is not None:
                normalized.append({"role": "assistant", "content": str(assistant_text)})

    return normalized


def run_agent(
    user_message: str,
    history: Any,
    thread_id: str,
    show_tools: bool,
):
    """Invoke the agent and append a response to chat history."""
    history = _normalize_history(history)
    clean_message = (user_message or "").strip()
    clean_thread_id = (thread_id or "default").strip() or "default"

    if not clean_message:
        status = f"Using thread_id: {clean_thread_id} | DB: {CHECKPOINT_DB_PATH}"
        return history, clean_thread_id, "", status

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": clean_message}]},
            config={"configurable": {"thread_id": clean_thread_id}},
        )
        final_answer = _extract_final_answer(result)

        if show_tools:
            tools = _extract_tool_names(result)
            if tools:
                tool_lines = "\n".join(f"- {name}" for name in tools)
                final_answer = f"Tools:\n{tool_lines}\n\n{final_answer}"

        history.append({"role": "user", "content": clean_message})
        history.append({"role": "assistant", "content": final_answer})
        status = f"Using thread_id: {clean_thread_id} | DB: {CHECKPOINT_DB_PATH}"
        return history, clean_thread_id, "", status
    except Exception as exc:
        history.append({"role": "user", "content": clean_message})
        history.append({"role": "assistant", "content": f"Error: {exc}"})
        status = f"Using thread_id: {clean_thread_id} | DB: {CHECKPOINT_DB_PATH}"
        return history, clean_thread_id, "", status


def set_new_thread() -> tuple[str, str]:
    """Generate and return a fresh thread id + status text."""
    new_id = _new_thread_id()
    status = f"Using thread_id: {new_id} | DB: {CHECKPOINT_DB_PATH}"
    return new_id, status


def clear_chat(thread_id: str) -> tuple[list[dict[str, str]], str]:
    """Clear visible chat history but keep the current thread id."""
    clean_thread_id = (thread_id or "default").strip() or "default"
    status = f"Using thread_id: {clean_thread_id} | DB: {CHECKPOINT_DB_PATH}"
    return [], status


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="LangGraph Research Agent") as demo:
        gr.Markdown("## LangGraph Research Agent")
        gr.Markdown("Chat with persistent memory using `thread_id` (SQLite checkpointing).")

        with gr.Row():
            thread_id = gr.Textbox(label="Thread ID", value="default", scale=3)
            new_thread_btn = gr.Button("New Thread", scale=1)
            clear_btn = gr.Button("Clear Chat", scale=1)

        show_tools = gr.Checkbox(label="Show tool names", value=True)
        status = gr.Markdown(f"Using thread_id: default | DB: {CHECKPOINT_DB_PATH}")

        chatbot = gr.Chatbot(label="Conversation", height=500)
        user_input = gr.Textbox(label="Your message", placeholder="Ask anything...", lines=2)
        send_btn = gr.Button("Send", variant="primary")

        send_btn.click(
            fn=run_agent,
            inputs=[user_input, chatbot, thread_id, show_tools],
            outputs=[chatbot, thread_id, user_input, status],
        )
        user_input.submit(
            fn=run_agent,
            inputs=[user_input, chatbot, thread_id, show_tools],
            outputs=[chatbot, thread_id, user_input, status],
        )

        new_thread_btn.click(
            fn=set_new_thread,
            inputs=None,
            outputs=[thread_id, status],
        )

        clear_btn.click(
            fn=clear_chat,
            inputs=[thread_id],
            outputs=[chatbot, status],
        )

    return demo


if __name__ == "__main__":
    app = build_ui()
    app.launch()
