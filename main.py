"""Run the agent in an interactive chat loop."""

from agent import agent

VERBOSE = True  # Set to False to hide the agent's internal steps


def print_steps(result: dict) -> None:
    """Print every message in the conversation to see what the agent did."""
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
        if VERBOSE:
            print_steps(result)
        else:
            print_response(result)


if __name__ == "__main__":
    main()
