"""Run the agent in an interactive chat loop."""

from agent import agent


def print_response(result: dict) -> None:
    """Print the last AI message from the agent response."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if msg.type == "ai" and msg.content:
            print(f"\n🤖  {msg.content}\n")
            return


def main() -> None:
    print("═" * 60)
    print("  LangGraph Agent  (type 'quit' to exit)")
    print("═" * 60)

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye! 👋")
            break

        result = agent.invoke({"messages": [{"role": "user", "content": user_input}]})
        print_response(result)


if __name__ == "__main__":
    main()
