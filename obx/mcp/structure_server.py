from typing import Optional
from mcp.server.fastmcp import FastMCP
from obx.utils.fs import list_vault_hierarchy, list_folder_contents

mcp = FastMCP("obx-structure")

@mcp.tool()
def list_vault_structure() -> str:
    """
    List the entire folder hierarchy of the Obsidian vault.
    Use this to understand the organization of the vault and find appropriate categories.
    """
    return list_vault_hierarchy()

@mcp.tool()
def inspect_folder(folder_path: str = ".") -> str:
    """
    List all files in a specific folder (non-recursive).
    Provides a 100-character snippet for markdown notes to help understand their content, and lists other file names.
    
    Args:
        folder_path: Relative path to the folder from the vault root (e.g., "Research/AI" or "." for root).
    """
    return list_folder_contents(folder_path)

if __name__ == "__main__":
    mcp.run()
