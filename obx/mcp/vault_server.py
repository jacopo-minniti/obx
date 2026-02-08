from typing import Optional, List
import re

from mcp.server.fastmcp import FastMCP

from obx.rag.engine import RAG
from obx.utils.fs import read_note, list_note_headers, write_note, list_notes, fuzzy_find


mcp = FastMCP("obx-vault")
_rag_engine: Optional[RAG] = None


def _clean(text: str) -> str:
    # Remove control chars that can break JSON parsing on some providers.
    if not text:
        return ""
    return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", " ", text)


def _get_rag() -> RAG:
    global _rag_engine
    if _rag_engine is None:
        _rag_engine = RAG()
    return _rag_engine


@mcp.tool()
def search_vault(query: str, limit: int = 7, weights: float = 0.5) -> str:
    """
    Search the vault for notes and snippets relevant to the query.
    Uses hybrid search (semantic + keyword).
    When crafting a query, favor intent-rich phrasing and expand with related terms,
    synonyms, abbreviations, adjacent concepts, and representative subtopics. If results
    are sparse, try alternate phrasings or more concrete instances to improve recall.
    """
    try:
        rag_engine = _get_rag()
        if not rag_engine.index_exists():
            return "Search index not found."
        results = rag_engine.search(query, limit=limit, weights=weights)
    except Exception as e:
        return f"Error: vault search unavailable ({e})."
    if not results:
        return "No relevant notes found in the vault."

    formatted = []
    for r in results:
        text = _clean(r.get("text", ""))
        source = r.get("source", "unknown")
        header = r.get("header")
        score = r.get("score", 0.0)

        source_display = f"{source} > {header}" if header else source
        header_line = f"Header: {header}\n" if header else ""
        formatted.append(
            f"--- Note: {source_display} (Score: {score:.2f}) ---\n"
            f"{header_line}"
            f"{text}\n"
        )

    return "\n".join(formatted)


@mcp.tool()
def read_note_tool(filename: str, header: Optional[str] = None) -> str:
    """Read the content of a markdown note in the vault."""
    return read_note(filename, header=header)


@mcp.tool()
def list_note_headers_tool(filename: str) -> str:
    """List headers in a markdown note."""
    return list_note_headers(filename)


@mcp.tool()
def write_note_tool(filename: str, content: str) -> str:
    """Create or overwrite a note with content."""
    return write_note(filename, content)


@mcp.tool()
def list_notes_tool(limit: int = 20) -> List[str]:
    """List recent notes in the vault."""
    return list_notes(limit)


@mcp.tool()
def fuzzy_find_tool(filename: str) -> str:
    """Find a file path by fuzzy matching the name."""
    return fuzzy_find(filename)


if __name__ == "__main__":
    mcp.run()
