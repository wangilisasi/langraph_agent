"""Run the agent in an interactive chat loop."""

from agent import agent

VERBOSE = False  # Default: show only the final answer (Perplexity-style)


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


def main() -> None:
    print("═" * 60)
    print("  LangGraph Agent  (type 'quit' to exit)")
    print("  Commands: /verbose on | /verbose off")
    print("═" * 60)

    verbose = VERBOSE

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

        try:
            result = agent.invoke({"messages": [{"role": "user", "content": user_input}]})
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
