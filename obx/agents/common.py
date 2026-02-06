from pydantic_ai.mcp import MCPServerStdio
import os
from obx.rag.engine import RAG
from obx.core.config import settings

# Initialize RAG globally
rag_engine = RAG()

# Initialize DuckDuckGo MCP Server
ddg_server = MCPServerStdio(
    'uvx',
    args=['duckduckgo-mcp-server'],
)

# Ensure API keys are set for providers
if settings.gemini_api_key:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    if "GOOGLE_API_KEY" in os.environ:
        del os.environ["GOOGLE_API_KEY"]
if settings.openai_api_key:
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key
