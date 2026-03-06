"""Run the agent in an interactive chat loop."""

import sqlite3
import uuid

from agent import agent, CHECKPOINT_DB_PATH

VERBOSE = False  # Default: show only the final answer (Perplexity-style)
HIDE_VERBOSE_TOOL_RESULTS = {"web_search", "web_search_deep", "fetch_page"}


def print_plan(result: dict) -> None:
    """Print the planner output for the current turn."""
    plan = result.get("plan", "")
    if not plan:
        return
    print("\nPlan:")
    print(plan)
    print()


def print_steps(result: dict) -> None:
    """Print every message in the conversation to see what the agent did."""
    print_plan(result)
    messages = result.get("messages", [])
    for msg in messages:
        if msg.type == "human":
            continue  # we already printed this
        elif msg.type == "ai" and msg.tool_calls:
            # The LLM decided to call a tool
            for tc in msg.tool_calls:
                print(f"  🔧 Tool call: {tc['name']}({tc['args']})")
        elif msg.type == "tool":
            # The tool returned a result
            if msg.name in HIDE_VERBOSE_TOOL_RESULTS:
                size = len(str(msg.content or ""))
                print(f"  📎 Tool result [{msg.name}]: [hidden raw output, {size} chars]")
            else:
                print(f"  📎 Tool result [{msg.name}]: {msg.content}")
        elif msg.type == "ai" and msg.content:
            # Final answer
            print(f"\n🤖  {msg.content}\n")


def print_response(result: dict) -> None:
    """Print the last AI message from the agent response."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if msg.type == "ai" and msg.content:
            print(f"\n🤖  {msg.content}\n")
            return


def print_tools_called(result: dict) -> None:
    """Print only the names of tools that were called in this turn."""
    messages = result.get("messages", [])
    tool_names: list[str] = []

    for msg in messages:
        if msg.type == "ai" and msg.tool_calls:
            for tc in msg.tool_calls:
                name = tc.get("name")
                if name:
                    tool_names.append(name)

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


def main() -> None:
    print("═" * 60)
    print("  LangGraph Agent  (type 'quit' to exit)")
    print("  Commands: /verbose on | /verbose off | /thread <id> | /newthread | /threads")
    print("═" * 60)

    verbose = VERBOSE
    thread_id = "default"

    saved_thread_ids = list_thread_ids()
    if saved_thread_ids:
        print("Saved threads found. Use Enter for default, /new for a fresh one, /threads to list, or enter an existing ID.")
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
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye! 👋")
            break

        if user_input.lower() == "/verbose on":
            verbose = True
            print("Verbose mode: ON")
            continue
        if user_input.lower() == "/verbose off":
            verbose = False
            print("Verbose mode: OFF")
            continue

        if user_input.lower() == "/threads":
            thread_ids = list_thread_ids()
            if not thread_ids:
                print("No saved threads found yet.")
            else:
                print("Saved thread IDs:")
                for saved_id in thread_ids:
                    marker = " (current)" if saved_id == thread_id else ""
                    print(f"- {saved_id}{marker}")
            continue

        if user_input.lower() == "/newthread":
            thread_id = new_thread_id()
            print(f"Created and switched to new thread_id: {thread_id}")
            continue

        if user_input.lower().startswith("/thread"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1 or not parts[1].strip():
                print("Usage: /thread <id>")
                print(f"Current thread_id: {thread_id}")
                continue
            thread_id = parts[1].strip()
            print(f"Switched thread_id to: {thread_id}")
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
        except Exception as e:
            print(f"\n❌  Error: {str(e)}")
            print("💡  Check your internet connection or API key.\n")


if __name__ == "__main__":
    main()
