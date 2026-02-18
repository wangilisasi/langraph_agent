"""Tools for a research agent that can search the web, read pages, and save findings."""

import os
import datetime
import json
import httpx
from pathlib import Path

from langchain_core.tools import tool, BaseTool
from pydantic import BaseModel, Field
from tavily import TavilyClient

# ── Tavily client (initialised once) ─────────────────────────────────────
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# Directory where the agent can save research output
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


# ═════════════════════════════════════════════════════════════════════════
#  FUNCTION-BASED TOOLS  (@tool decorator)
# ═════════════════════════════════════════════════════════════════════════


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for current information using Tavily.

    Use this when you need up-to-date facts, news, documentation, or anything
    that may not be in your training data.

    Args:
        query: The search query — be specific for better results.
        max_results: Number of results to return (default 5, max 10).
    """
    try:
        response = tavily.search(
            query=query,
            max_results=min(max_results, 10),
            search_depth="basic",
        )
        results = []
        for r in response.get("results", []):
            results.append(
                f"**{r['title']}**\n"
                f"URL: {r['url']}\n"
                f"{r['content']}\n"
            )
        return "\n---\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Search error: {e}"


@tool
def web_search_deep(query: str) -> str:
    """Perform an in-depth web search with full content extraction.

    Use this when you need comprehensive, detailed information on a topic —
    slower but returns richer content than web_search.

    Args:
        query: The search query.
    """
    try:
        response = tavily.search(
            query=query,
            max_results=3,
            search_depth="advanced",
            include_raw_content=True,
        )
        results = []
        for r in response.get("results", []):
            content = r.get("raw_content", r["content"])
            # Truncate to avoid overwhelming the context
            if len(content) > 3000:
                content = content[:3000] + "... [truncated]"
            results.append(
                f"**{r['title']}**\n"
                f"URL: {r['url']}\n"
                f"{content}\n"
            )
        return "\n---\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Deep search error: {e}"


@tool
def fetch_page(url: str) -> str:
    """Fetch and return the text content of a web page.

    Use this when you have a specific URL and need to read its content.

    Args:
        url: The full URL to fetch (must start with http:// or https://).
    """
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=15)
        resp.raise_for_status()
        # Return raw text, truncated to avoid context overload
        text = resp.text[:5000]
        if len(resp.text) > 5000:
            text += "\n... [truncated — page is longer]"
        return text
    except Exception as e:
        return f"Failed to fetch {url}: {e}"


@tool
def get_current_datetime() -> str:
    """Return the current date, time, and day of the week."""
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y — %H:%M:%S")


@tool
def save_to_file(filename: str, content: str) -> str:
    """Save text content to a file in the output/ directory.

    Use this to save research findings, summaries, or reports.

    Args:
        filename: Name of the file (e.g. 'research.md', 'notes.txt').
        content: The text content to write.
    """
    try:
        filepath = OUTPUT_DIR / filename
        filepath.write_text(content, encoding="utf-8")
        return f"Saved to {filepath.resolve()}"
    except Exception as e:
        return f"Error saving file: {e}"


@tool
def read_file(filename: str) -> str:
    """Read the contents of a file from the output/ directory.

    Args:
        filename: Name of the file to read.
    """
    try:
        filepath = OUTPUT_DIR / filename
        if not filepath.exists():
            return f"File not found: {filename}"
        content = filepath.read_text(encoding="utf-8")
        if len(content) > 5000:
            content = content[:5000] + "\n... [truncated]"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def list_saved_files() -> str:
    """List all files in the output/ directory."""
    files = list(OUTPUT_DIR.iterdir())
    if not files:
        return "No files saved yet."
    return "\n".join(f"  - {f.name} ({f.stat().st_size} bytes)" for f in files)


# ═════════════════════════════════════════════════════════════════════════
#  CLASS-BASED TOOL  (BaseTool subclass — for comparison)
# ═════════════════════════════════════════════════════════════════════════


class QuickAnswerInput(BaseModel):
    """Input for the Tavily Q&A endpoint."""
    question: str = Field(description="A direct question to answer from the web")


class QuickAnswerTool(BaseTool):
    """Get a direct, concise answer to a factual question from the web.

    Unlike web_search which returns multiple results, this returns a single
    short answer — like a search engine's featured snippet.
    """

    name: str = "quick_answer"
    description: str = (
        "Get a direct short answer to a factual question from the web. "
        "Best for simple factual questions like 'What is the population of Kenya?' "
        "or 'Who won the 2024 Champions League?'"
    )
    args_schema: type[BaseModel] = QuickAnswerInput

    def _run(self, question: str) -> str:
        try:
            response = tavily.qna_search(query=question)
            return response if response else "No direct answer found."
        except Exception as e:
            return f"Quick answer error: {e}"


quick_answer = QuickAnswerTool()
