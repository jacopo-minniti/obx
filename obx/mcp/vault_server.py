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
        formatted.append(f"--- Note: {source_display} (Score: {score:.2f}) ---\n{text}\n")

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


# --- Learning Tools ---

@mcp.tool()
def get_flashcards_tool(filename: str) -> str:
    """
    Get all flashcards from a note.
    Returns flashcards with their current SRS state.
    """
    from obx.core.learning_parser import parse_flashcards
    
    content = read_note(filename)
    if content.startswith("Error:"):
        return content
    
    parsed = parse_flashcards(content)
    if not parsed:
        return "No flashcards found in this note."
    
    result = []
    for p in parsed:
        card = p.item
        result.append(
            f"Q: {card.question}\n"
            f"A: {card.answer}\n"
            f"State: {card.state.value}, Due: {card.due_date}, Ease: {card.ease}"
        )
    return "\n---\n".join(result)


@mcp.tool()
def get_exercises_tool(filename: str) -> str:
    """
    Get all exercises from a note.
    Returns exercises with their current grade and progress.
    """
    from obx.core.learning_parser import parse_exercises
    
    content = read_note(filename)
    if content.startswith("Error:"):
        return content
    
    parsed = parse_exercises(content)
    if not parsed:
        return "No exercises found in this note."
    
    result = []
    for p in parsed:
        ex = p.item
        result.append(
            f"Prompt: {ex.prompt[:200]}{'...' if len(ex.prompt) > 200 else ''}\n"
            f"Difficulty: {ex.difficulty}, Grade: {ex.grade.name}, Attempts: {ex.attempts}"
        )
    return "\n---\n".join(result)


@mcp.tool()
def get_learning_status_tool(filename: str) -> str:
    """
    Get the overall learning status for a note.
    Returns memory and exercise scores from YAML frontmatter.
    """
    from obx.utils.fs import get_learning_scores
    
    scores = get_learning_scores(filename)
    return (
        f"Memory Score: {scores['memory']:.0%}\n"
        f"Exercise Score: {scores['exercise']:.0%}"
    )


@mcp.tool()
def get_due_flashcards_tool(filename: str) -> str:
    """
    Get flashcards that are currently due for review.
    """
    from obx.core.learning_parser import parse_flashcards
    from datetime import datetime
    
    content = read_note(filename)
    if content.startswith("Error:"):
        return content
    
    parsed = parse_flashcards(content)
    now = datetime.now()
    due = [p for p in parsed if p.item.is_due(now)]
    
    if not due:
        return "No flashcards due for review."
    
    result = []
    for p in due:
        card = p.item
        result.append(f"Q: {card.question}")
    
    return f"{len(due)} flashcards due:\n" + "\n".join(result)


if __name__ == "__main__":
    mcp.run()
