"""Run the agent in an interactive chat loop."""

from agent import agent


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


def main() -> None:
    print("=" * 50)
    print("  LangGraph Agent  (type 'q' to quit)")
    print("=" * 50)

    thread_id = "default"
    print(f"Thread: {thread_id}\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config={"configurable": {"thread_id": thread_id}},
            )

            # Show which tools were called (if any)
            tool_names = extract_tools_called(result)
            if tool_names:
                print("Tools:", ", ".join(tool_names))

            # Show the final answer
            response = extract_last_ai_response(result)
            if response:
                print(f"\nA: {response}\n")

        except Exception as e:
            print(f"\nError: {e}")
            print("Tip: Check your internet connection or API key.\n")


if __name__ == "__main__":
    main()
