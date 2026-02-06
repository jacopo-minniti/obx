from pydantic_ai import Agent, RunContext
from typing import List, Optional
from obx.core.config import settings
from obx.utils.fs import read_note, write_note, list_notes, fuzzy_find
from obx.agents.common import rag_engine, ddg_server

# --- Main Agent ("obx chat") ---
obx_agent = Agent(
    model=settings.reasoning_model,
    system_prompt=(
        f"You are obx, an intelligent assistant for the user's Obsidian vault. "
        f"The user's mood preference is: {settings.mood}. "
        "You verify information by reading notes or searching the vault. "
        "When asked to write, you use the available tools to save files. "
        "Always cite the source note when answering from knowledge. "
        "You should always prioritize the knowledge of the vault, however if you believe for some question "
        "you need specifically web search (confirming an information you are in doubt of or finding something "
        "specific which is not already in the vault or you do not know) then you can use the duckduck go web search tool."
    ),
    deps_type=None,
    toolsets=[ddg_server]
)

@obx_agent.tool
def semantic_search(ctx: RunContext, query: str) -> str:
    """
    Search the vault for notes relevant to the query using semantic search.
    Returns a list of matching text chunks with their source filenames.
    """
    if not rag_engine.index_exists():
        return "Search index not found. Please tell the user to run 'obx explain' or 'obx index' first."
    
    results = rag_engine.search(query, limit=5)
    if not results:
        return "No relevant notes found."
    
    formatted = []
    for r in results:
        text = r.get('text', '')
        source = r.get('source', 'unknown')
        score = r.get('score', 0.0)
        formatted.append(f"--- Note: {source} (Score: {score:.2f}) ---\n{text}\n")
    
    return "\n".join(formatted)

@obx_agent.tool
def read_note_tool_chat(ctx: RunContext, filename: str, header: Optional[str] = None) -> str:
    """Read the content of a markdown note."""
    return read_note(filename, header=header)

@obx_agent.tool
def write_note_tool(ctx: RunContext, filename: str, content: str) -> str:
    """Create or overwrite a note with content."""
    return write_note(filename, content)

@obx_agent.tool
def list_notes_tool(ctx: RunContext, limit: int = 20) -> List[str]:
    """List recent notes in the vault."""
    return list_notes(limit)

@obx_agent.tool
def fuzzy_find_tool(ctx: RunContext, filename: str) -> str:
    """Find a file path by fuzzy matching the name."""
    return fuzzy_find(filename)
