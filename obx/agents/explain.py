from pydantic_ai import Agent, RunContext
from typing import Optional
from obx.core.config import settings
from obx.utils.fs import read_note
from obx.agents.common import rag_engine, ddg_server

# --- Explain Agent ("obx explain") ---
explain_agent = Agent(
    model=settings.primary_model,
    system_prompt=(
        f"You are a helpful assistant explaining topics based on the user's Obsidian vault. "
        f"Use the 'search_vault' tool to find relevant information and 'read_note' to see full note contents if needed. "
        f"Synthesize the information clearly and concisely. "
        f"IMPORTANT: You MUST cite your sources. When using information from a note, verify the source filename and cite it in your response (e.g., '...[Source: Note Name]'). "
        "You should always prioritize the knowledge of the vault, however if you believe for some question "
        "you need specifically web search (confirming an information you are in doubt of or finding something "
        "specific which is not already in the vault or you do not know) then you can use the duckduck go web search tool."
    ),
    deps_type=None,
    toolsets=[ddg_server]
)

@explain_agent.tool
def search_vault(ctx: RunContext, query: str) -> str:
    """
    Search the vault for notes and snippets relevant to the query. 
    Uses hybrid search (semantic + keyword).
    """
    if not rag_engine.index_exists():
        return "Search index not found."
        
    results = rag_engine.search(query, limit=7, weights=0.5) 
    
    if not results:
        return "No relevant notes found in the vault."
        
    formatted = []
    for r in results:
        text = r.get('text', '')
        source = r.get('source', 'unknown')
        score = r.get('score', 0.0)
        formatted.append(f"--- Note: {source} (Score: {score:.2f}) ---\n{text}\n")
    
    return "\n".join(formatted)

@explain_agent.tool
def read_note_tool(ctx: RunContext, filename: str, header: Optional[str] = None) -> str:
    """
    Read the content of a markdown note in the vault. 
    Can read specific sections if 'header' is provided.
    """
    return read_note(filename, header=header)
