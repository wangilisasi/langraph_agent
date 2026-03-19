"""Tools for a research agent that can search the web, read pages, and save findings."""

import datetime
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from tavily import TavilyClient

# Tavily client (initialized once)
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# Directory where the agent can save research output
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}


def _truncate_text(text: str, limit: int) -> str:
    """Truncate text to a character limit with a clear suffix."""
    if len(text) <= limit:
        return text
    return text[:limit] + "... [truncated]"


def _normalize_text(text: str) -> str:
    """Normalize text spacing for cleaner excerpts."""
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _format_search_results(results: list[dict]) -> str:
    """Format Tavily search results with numbered citations."""
    if not results:
        return "No results found."

    blocks: list[str] = []
    sources: list[str] = []

    for idx, result in enumerate(results, start=1):
        title = result.get("title") or "Untitled result"
        url = result.get("url") or ""

        content = result.get("content", "") or ""
        content = _normalize_text(content)
        if not content:
            content = "(No excerpt returned.)"

        blocks.append(
            f"[{idx}] {title}\n"
            f"URL: {url}\n"
            f"Excerpt: {content}"
        )
        if url:
            sources.append(f"[{idx}] {url}")

    output = "\n\n---\n\n".join(blocks)
    if sources:
        output += "\n\nSources:\n" + "\n".join(sources)
    return output


def _resolve_output_path(filename: str) -> Path:
    """Resolve a filename inside output/ and block path traversal."""
    base_dir = OUTPUT_DIR.resolve()
    filepath = (OUTPUT_DIR / filename).resolve()
    if filepath != base_dir and base_dir not in filepath.parents:
        raise ValueError("Filename must stay within output/ directory")
    return filepath


def _is_valid_http_url(url: str) -> bool:
    """Validate that a URL has an HTTP(S) scheme and a hostname."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _html_to_text(html: str) -> str:
    """Convert HTML into readable plain text."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "canvas"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    return _normalize_text(text)


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for current information using Tavily.

    Use this when you need up-to-date facts, news, docs, or references.

    Args:
        query: The search query. Be specific for better results.
        max_results: Number of results to return (default 5, max 10).
    """
    try:
        response = tavily.search(
            query=query,
            max_results=min(max_results, 10),
            search_depth="basic",
        )
        return _format_search_results(response.get("results", []))
    except Exception as e:
        return f"Search error: {e}"


@tool
def fetch_page(url: str) -> str:
    """Fetch a page and return readable text with a citation URL.

    Use this when you already have a specific URL and need content from it.

    Args:
        url: The full URL to fetch (must start with http:// or https://).
    """
    if not _is_valid_http_url(url):
        return "Invalid URL. Please provide a full http(s) URL."

    try:
        resp = httpx.get(
            url,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=20,
        )
        resp.raise_for_status()

        content_type = (resp.headers.get("content-type") or "").lower()

        if "text/html" in content_type:
            body_text = _html_to_text(resp.text)
            if not body_text:
                body_text = _normalize_text(resp.text)
        elif "text/" in content_type or "json" in content_type or "xml" in content_type:
            body_text = _normalize_text(resp.text)
        else:
            return (
                f"Fetched URL: {resp.url}\n"
                f"Content-Type: {content_type or 'unknown'}\n"
                "This appears to be a binary or unsupported document type."
            )

        snippet = _truncate_text(body_text, 7000)
        return (
            f"Source: {resp.url}\n"
            f"Content-Type: {content_type or 'unknown'}\n\n"
            f"{snippet}"
        )
    except Exception as e:
        return f"Failed to fetch {url}: {e}"


@tool
def get_current_datetime() -> str:
    """Return the current date, time, and day of the week."""
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y - %H:%M:%S")


@tool
def save_to_file(filename: str, content: str) -> str:
    """Save text content to a file in the output/ directory.

    Use this to save research findings, summaries, or reports.

    Args:
        filename: Name of the file (for example, 'research.md').
        content: The text content to write.
    """
    try:
        filepath = _resolve_output_path(filename)
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
        filepath = _resolve_output_path(filename)
        if not filepath.exists():
            return f"File not found: {filename}"
        content = filepath.read_text(encoding="utf-8")
        if len(content) > 5000:
            content = content[:5000] + "\n... [truncated]"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def run_python_code(code: str) -> str:
    """Run Python code locally and return the output (stdout/stderr).

    Use this when you need to calculate math, analyze data, process JSON,
    or do any programming task to get the answer. 

    Args:
        code: A string containing valid Python code. You can print() results to see them.
    """
    script_path = OUTPUT_DIR / "temp_script.py"
    try:
        script_path.write_text(code, encoding="utf-8")
        
        result = subprocess.run(
            ["python", str(script_path)],
            capture_output=True,
            text=True,
            timeout=10  # Prevent infinite loops
        )
        
        output = result.stdout
        if result.stderr:
            output += f"\nErrors:\n{result.stderr}"
            
        if not output.strip():
            return "Code executed successfully but returned no output. Did you forget to print()?"
            
        return _truncate_text(output, 2000)
    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out after 10 seconds."
    except Exception as e:
        return f"Error executing code: {e}"
    finally:
        if script_path.exists():
            script_path.unlink()  # Clean up the temp file


@tool
def run_terminal_command(command: str) -> str:
    """Run a terminal/command line prompt natively on the computer.

    Use this when you need to run things like `dir`, `git status`, system checks, 
    or any other native OS commands. Note that it runs on a Windows machine.

    Args:
        command: The terminal command to execute.
    """
    try:
        # We use shell=True to run standard shell commands
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,  # Prevent infinite hangs
        )
        
        output = result.stdout
        if result.stderr:
            output += f"\n[Errors/Warnings]:\n{result.stderr}"
            
        if not output.strip():
            return f"Command '{command}' executed successfully but returned no output."
            
        return _truncate_text(output, 2000)
    except subprocess.TimeoutExpired:
        return f"Error: Command '{command}' timed out after 15 seconds."
    except Exception as e:
        return f"Error executing command: {e}"

