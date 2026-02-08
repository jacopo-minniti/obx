from pydantic_ai.mcp import MCPServerStdio
import os
import sys
from obx.core.config import settings

# Initialize Vault MCP Server
vault_server = MCPServerStdio(
    sys.executable,
    args=["-m", "obx.mcp.vault_server"],
)

# DuckDuckGo MCP Server is disabled until its dependency constraints
# are compatible with the latest pydantic-ai stack.

# Ensure API keys are set for providers
if settings.gemini_api_key:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    if "GOOGLE_API_KEY" in os.environ:
        del os.environ["GOOGLE_API_KEY"]
if settings.openai_api_key:
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key
if settings.openrouter_api_key:
    os.environ["OPENROUTER_API_KEY"] = settings.openrouter_api_key
