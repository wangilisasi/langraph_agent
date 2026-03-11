"""Tools for a research agent that can search the web, read pages, and save findings."""

import datetime
import os
import re
import sys
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

AUTO_APPROVE_FILE_WRITES = os.getenv("AUTO_APPROVE_FILE_WRITES", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

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


def _format_search_results(results: list[dict], content_key: str, max_chars: int | None = None) -> str:
    """Format Tavily search results with explicit numbered citations."""
    if not results:
        return "No results found."

    blocks: list[str] = []
    sources: list[str] = []

    for idx, result in enumerate(results, start=1):
        title = result.get("title") or "Untitled result"
        url = result.get("url") or ""

        content = result.get(content_key, result.get("content", "")) or ""
        content = _normalize_text(content)
        if max_chars is not None:
            content = _truncate_text(content, max_chars)
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


def _approve_save(filename: str, content: str) -> tuple[bool, str]:
    """Ask for confirmation before writing to disk."""
    if AUTO_APPROVE_FILE_WRITES:
        return True, ""

    if not sys.stdin or not sys.stdin.isatty():
        return False, (
            "Save blocked: non-interactive session. "
            "Set AUTO_APPROVE_FILE_WRITES=1 to allow automatic writes."
        )

    preview = _truncate_text(content, 400)
    print("\n[Approval required] save_to_file")
    print(f"- Target file: output/{filename}")
    print("- Content preview:")
    print(preview)
    decision = input("Approve file write? [y/N]: ").strip().lower()
    if decision in {"y", "yes"}:
        return True, ""
    return False, "Save cancelled by user."


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

    # Remove non-content elements before extracting text.
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
        return _format_search_results(response.get("results", []), content_key="content")
    except Exception as e:
        return f"Search error: {e}"


@tool
def web_search_deep(query: str) -> str:
    """Perform an in-depth web search with full content extraction.

    Use this when you need detailed information. It is slower but richer
    than web_search.

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
        return _format_search_results(
            response.get("results", []),
            content_key="raw_content",
            max_chars=3000,
        )
    except Exception as e:
        return f"Deep search error: {e}"


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
        approved, reason = _approve_save(filename, content)
        if not approved:
            return reason

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
def list_saved_files() -> str:
    """List all files in the output/ directory."""
    files = list(OUTPUT_DIR.iterdir())
    if not files:
        return "No files saved yet."
    return "\n".join(f"  - {f.name} ({f.stat().st_size} bytes)" for f in files)


@tool
def quick_answer(question: str) -> str:
    """Return a concise answer and citation for simple factual questions.

    Args:
        question: The factual question to answer.
    """
    try:
        response = tavily.search(query=question, max_results=1, search_depth="basic")
        results = response.get("results", [])
        if results:
            top = results[0]
            excerpt = _normalize_text(top.get("content", ""))
            excerpt = _truncate_text(excerpt, 1000) if excerpt else "No short excerpt returned."
            title = top.get("title") or "Top result"
            url = top.get("url") or ""
            return (
                f"Answer candidate from top source ({title}):\n"
                f"{excerpt}\n\n"
                f"Source: {url}"
            )

        fallback = tavily.qna_search(query=question)
        if fallback:
            return f"{fallback}\n\nSource: Tavily quick answer (no URL provided)."
        return "No direct answer found."
    except Exception as e:
        return f"Quick answer error: {e}"

