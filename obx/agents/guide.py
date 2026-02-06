from pydantic_ai import Agent, RunContext
from typing import Optional
from obx.core.config import settings
from obx.utils.fs import read_note
from obx.agents.common import rag_engine, ddg_server

# --- Study Guide Agent ("obx make guide") ---
study_guide_agent = Agent(
    model=settings.primary_model,
    system_prompt=(
        "You are an expert tutor creating a personalized study guide. "
        "The user will provide sources (PDFs, notes, or URLs). "
        "Your goal is to synthesize this information into a structured guide. "
        "Structure your response as follows:\n"
        "1. **Overview & Structure**: Brief summary of the content and how the sources relate.\n"
        "2. **Key Concepts & Advice**: The core of the guide. What matters most? What should the student focus on to gain deep understanding?\n"
        "3. **Exercises & Practice**: Suggest specific exercises or problems from the text/sources that are crucial. Explain why.\n"
        "4. **Vault Connections**: If context from the user's vault is provided, explicitly connect the new material to their existing notes. Cite these connections using '...[Source: Note Name]'.\n\n"
        "If the user provides a specific 'Focus', tailor the entire guide around that topic."
        "Use the 'search_vault_for_guide' tool to find relevant context in the user's vault if needed."
        "Use the 'read_context_note' tool to fetch full content of referenced notes."
    ),
    deps_type=None,
    toolsets=[ddg_server]
)

@study_guide_agent.tool
def search_vault_for_guide(ctx: RunContext, query: str) -> str:
    """
    Search the vault for notes relevant to the query to contextualize the study guide.
    """
    if not rag_engine.index_exists():
        return "Search index not found. Contextualization unavailable."
    
    results = rag_engine.search(query, limit=5, weights=0.5)
    if not results:
        return "No relevant context found in vault."
    
    formatted = []
    for r in results:
        text = r.get('text', '')
        source = r.get('source', 'unknown')
        formatted.append(f"--- Context from Note: {source} ---\n{text}\n")
    
    return "\n".join(formatted)

@study_guide_agent.tool
def read_context_note(ctx: RunContext, filename: str, header: Optional[str] = None) -> str:
    """
    Read full content of a note found in the vault for deeper context.
    Use 'header' to read only a specific relevant section if known.
    """
    return read_note(filename, header=header)
