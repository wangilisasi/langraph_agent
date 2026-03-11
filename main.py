"""Run the agent in an interactive chat loop."""

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from agent import agent, CHECKPOINT_DB_PATH

VERBOSE = False  # Default: show only the final answer (Perplexity-style)
HIDE_VERBOSE_TOOL_RESULTS = {"web_search", "web_search_deep", "fetch_page"}
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def print_plan(result: dict) -> None:
    """Print the planner output for the current turn."""
    plan = result.get("plan", "")
    if not plan:
        return
    print("\nPlan:")
    print(plan)
    print()


def extract_last_ai_response(result: dict) -> str:
    """Return the last AI message content from the agent response."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if msg.type == "ai" and msg.content:
            return str(msg.content)
    return ""


def extract_tools_called(result: dict) -> list[str]:
    """Return deduplicated tool names called in this turn."""
    messages = result.get("messages", [])
    tool_names: list[str] = []
    seen: set[str] = set()

    for msg in messages:
        if msg.type == "ai" and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name")
                if name and name not in seen:
                    tool_names.append(name)
                    seen.add(name)

    return tool_names


def print_steps(result: dict) -> None:
    """Print every message in the conversation to see what the agent did."""
    print_plan(result)
    messages = result.get("messages", [])
    for msg in messages:
        if msg.type == "human":
            continue  # already shown as user input
        if msg.type == "ai" and msg.tool_calls:
            for tc in msg.tool_calls:
                print(f"  [tool-call] {tc['name']}({tc['args']})")
            continue
        if msg.type == "tool":
            if msg.name in HIDE_VERBOSE_TOOL_RESULTS:
                size = len(str(msg.content or ""))
                print(f"  [tool-result:{msg.name}] [hidden raw output, {size} chars]")
            else:
                print(f"  [tool-result:{msg.name}] {msg.content}")
            continue
        if msg.type == "ai" and msg.content:
            print(f"\nAssistant: {msg.content}\n")


def print_response(result: dict) -> None:
    """Print the last AI message from the agent response."""
    response = extract_last_ai_response(result)
    if response:
        print(f"\nAssistant: {response}\n")


def print_tools_called(result: dict) -> None:
    """Print only the names of tools that were called in this turn."""
    tool_names = extract_tools_called(result)
    if not tool_names:
        return

    print("Tools:")
    for name in tool_names:
        print(f"- {name}")


def list_thread_ids() -> list[str]:
    """Return distinct thread IDs found in the checkpoint database."""
    try:
        with sqlite3.connect(CHECKPOINT_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            table_names = [row[0] for row in cursor.fetchall()]

            found_ids: set[str] = set()
            for table_name in table_names:
                if "checkpoint" not in table_name.lower():
                    continue
                try:
                    cursor.execute(f"SELECT DISTINCT thread_id FROM {table_name}")
                    found_ids.update(
                        thread_id
                        for (thread_id,) in cursor.fetchall()
                        if isinstance(thread_id, str) and thread_id.strip()
                    )
                except sqlite3.OperationalError:
                    continue

            return sorted(found_ids)
    except sqlite3.Error:
        return []


def new_thread_id() -> str:
    """Generate a short unique thread ID."""
    return f"thread-{uuid.uuid4().hex[:8]}"


def _resolve_output_path(filename: str) -> Path:
    """Resolve a filename under output/ and block path traversal."""
    base_dir = OUTPUT_DIR.resolve()
    filepath = (OUTPUT_DIR / filename).resolve()
    if filepath != base_dir and base_dir not in filepath.parents:
        raise ValueError("Filename must stay within output/ directory")
    return filepath


def save_text_to_output(filename: str, content: str) -> str:
    """Save text content into output/<filename>."""
    filepath = _resolve_output_path(filename)
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def print_help() -> None:
    """Print supported interactive commands."""
    print("Commands:")
    print("- /help")
    print("- /verbose on")
    print("- /verbose off")
    print("- /threads")
    print("- /thread <id>")
    print("- /newthread")
    print("- /history [n]      (show recent turn history for this session)")
    print("- /save <filename>  (save last assistant response to output/<filename>)")
    print("- quit | exit | q")


def parse_history_limit(user_input: str) -> int | None:
    """Parse optional history limit from '/history [n]' command."""
    parts = user_input.split(maxsplit=1)
    if len(parts) == 1:
        return 10

    try:
        value = int(parts[1].strip())
    except ValueError:
        return None

    if value <= 0:
        return None
    return value


def print_history(history: list[dict[str, Any]], limit: int) -> None:
    """Print recent session turns."""
    if not history:
        print("No history yet in this session.")
        return

    count = min(limit, len(history))
    print(f"Showing last {count} turns:")

    start_idx = len(history) - count + 1
    for idx, item in enumerate(history[-count:], start=start_idx):
        print(f"\nTurn {idx}")
        print(f"User: {item['user']}")
        if item["tools"]:
            print(f"Tools: {', '.join(item['tools'])}")
        print(f"Assistant: {item['assistant']}")


def main() -> None:
    print("=" * 60)
    print("  LangGraph Agent  (type 'quit' to exit)")
    print("  Type /help to see all commands")
    print("=" * 60)

    verbose = VERBOSE
    thread_id = "default"
    session_history: list[dict[str, Any]] = []
    last_assistant_response = ""

    saved_thread_ids = list_thread_ids()
    if saved_thread_ids:
        print(
            "Saved threads found. Use Enter for default, /new for a fresh one, "
            "/threads to list, or enter an existing ID."
        )
        while True:
            initial_choice = input("Thread to start with: ").strip()
            if not initial_choice:
                break

            lower_choice = initial_choice.lower()
            if lower_choice == "/new":
                thread_id = new_thread_id()
                break
            if lower_choice == "/threads":
                print("Saved thread IDs:")
                for saved_id in saved_thread_ids:
                    print(f"- {saved_id}")
                continue

            thread_id = initial_choice
            break

    print(f"Using thread_id: {thread_id}")

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue

        lower_input = user_input.lower()
        if lower_input in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        if lower_input == "/help":
            print_help()
            continue

        if lower_input == "/verbose on":
            verbose = True
            print("Verbose mode: ON")
            continue
        if lower_input == "/verbose off":
            verbose = False
            print("Verbose mode: OFF")
            continue

        if lower_input == "/threads":
            thread_ids = list_thread_ids()
            if not thread_ids:
                print("No saved threads found yet.")
            else:
                print("Saved thread IDs:")
                for saved_id in thread_ids:
                    marker = " (current)" if saved_id == thread_id else ""
                    print(f"- {saved_id}{marker}")
            continue

        if lower_input == "/newthread":
            thread_id = new_thread_id()
            print(f"Created and switched to new thread_id: {thread_id}")
            continue

        if lower_input.startswith("/thread"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1 or not parts[1].strip():
                print("Usage: /thread <id>")
                print(f"Current thread_id: {thread_id}")
                continue
            thread_id = parts[1].strip()
            print(f"Switched thread_id to: {thread_id}")
            continue

        if lower_input.startswith("/history"):
            limit = parse_history_limit(user_input)
            if limit is None:
                print("Usage: /history [n]  (n must be a positive integer)")
                continue
            print_history(session_history, limit)
            continue

        if lower_input.startswith("/save"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                print("Usage: /save <filename>")
                continue
            if not last_assistant_response:
                print("No assistant response to save yet.")
                continue
            try:
                save_path = save_text_to_output(parts[1].strip(), last_assistant_response)
                print(f"Saved last assistant response to {save_path}")
            except Exception as e:
                print(f"Save failed: {e}")
            continue

        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config={"configurable": {"thread_id": thread_id}},
            )

            if verbose:
                print_steps(result)
            else:
                print_tools_called(result)
                print_response(result)

            last_assistant_response = extract_last_ai_response(result)
            session_history.append(
                {
                    "user": user_input,
                    "assistant": last_assistant_response,
                    "tools": extract_tools_called(result),
                }
            )
        except Exception as e:
            print(f"\nError: {str(e)}")
            print("Tip: Check your internet connection or API key.\n")


if __name__ == "__main__":
    main()

