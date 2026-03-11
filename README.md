# LangGraph Research Agent

A local Python CLI research agent built with LangGraph, LangChain tools, OpenRouter, and Tavily.

## What it does

- Runs an interactive chat loop in the terminal
- Uses a planner + tool-calling agent graph
- Searches the web and fetches specific pages
- Saves notes/reports to `output/`
- Persists conversation checkpoints in SQLite by thread ID

## Requirements

- Windows PowerShell (or any shell)
- Python 3.10+
- API keys:
  - `OPENROUTER_API_KEY`
  - `TAVILY_API_KEY`

## Quick start (PowerShell)

```powershell
cd "C:\Users\Emil P\Desktop\Web Dev\langraph_agent"

# Create and activate a fresh virtual environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
Copy-Item .env.example .env
# Then edit .env and add your real API keys

# Run the agent
python .\main.py
```

If `python` is not on PATH, use:

```powershell
.\.venv\Scripts\python.exe .\main.py
```

## CLI commands

- `/help`
- `/verbose on`
- `/verbose off`
- `/threads`
- `/thread <id>`
- `/newthread`
- `/history [n]`
- `/save <filename>`
- `quit` / `exit` / `q`

## Files

- `main.py`: interactive CLI loop and user commands
- `agent.py`: LangGraph state machine, planner/chatbot/tool routing, checkpointing
- `tools.py`: web/search/file tools used by the agent
- `output/agent_checkpoints.db`: SQLite checkpoint storage (auto-created)

## Notes

- `save_to_file` asks for approval by default in interactive sessions.
- Set `AUTO_APPROVE_FILE_WRITES=1` in `.env` to skip save prompts.
- `fetch_page` now extracts readable text from HTML and returns source citations.

