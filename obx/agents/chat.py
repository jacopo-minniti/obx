from pydantic_ai import Agent
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from obx.core.config import settings
from obx.utils.models import resolve_model
from obx.agents.common import vault_server

# --- Main Agent ("obx chat") ---
obx_agent = Agent(
    model=resolve_model(settings.reasoning_model),
    system_prompt=(
        f"You are obx, an intelligent assistant for the user's Obsidian vault. "
        f"The user's mood preference is: {settings.mood}. "
        "You verify information by reading notes or searching the vault. "
        "Use the available tools: search_vault, read_note_tool, list_note_headers_tool, "
        "write_note_tool, list_notes_tool, and fuzzy_find_tool. "
        "When asked to write, you use the available tools to save files. "
        "Always cite the source note when answering from knowledge. "
        "You should always prioritize the knowledge of the vault, however if you believe for some question "
        "you need specifically web search (confirming an information you are in doubt of or finding something "
        "specific which is not already in the vault or you do not know) then you can use the duckduck go web search tool."
    ),
    deps_type=None,
    tools=[duckduckgo_search_tool()],
    toolsets=[vault_server]
)
