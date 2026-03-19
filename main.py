"""Run the agent in an interactive chat loop."""

from agent import agent


def extract_last_ai_response(result: dict) -> str:
    """Return the last AI message content from the agent response."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if msg.type == "ai" and msg.content:
            return str(msg.content)
    return ""


def extract_tool_calls(result: dict) -> list[dict]:
    """Return all tool calls made in this turn."""
    messages = result.get("messages", [])
    tool_calls = []
    
    for msg in messages:
        if msg.type == "ai" and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(tc)

    return tool_calls


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
                {"messages": [HumanMessage(content=user_input)]},
                config={"configurable": {"thread_id": thread_id}},
            )

            # Show which tools were called and their arguments
            t_calls = extract_tool_calls(result)
            if t_calls:
                print("Tools Used: ")
                for tc in t_calls:
                    name = tc.get("name")
                    args = tc.get("args", {})
                    print(f"- {name}")
                    for key, val in args.items():
                        # If the value is multiline (like python code), format it nicely
                        if isinstance(val, str) and "\n" in val:
                            print(f"  {key}:")
                            for line in val.split("\n"):
                                print(f"    {line}")
                        else:
                            print(f"  {key}: {val}")
                print()

            # Show the final answer
            response = extract_last_ai_response(result)
            if response:
                print(f"\nA: {response}\n")

        except Exception as e:
            print(f"\nError: {e}")
            print("Tip: Check your internet connection or API key.\n")


if __name__ == "__main__":
    main()
