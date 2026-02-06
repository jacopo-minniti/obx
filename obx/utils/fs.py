import os
import re
from pathlib import Path
from typing import List, Optional
from obx.core.config import settings

def _get_vault_path() -> Path:
    if not settings.vault_path:
        raise ValueError("Vault path not configured. Run 'obx config' first.")
    return settings.vault_path

def read_note(filename: str, header: Optional[str] = None) -> str:
    """Reads the content of a markdown note in the vault, optionally focusing on a specific header."""
    vault = _get_vault_path()
    # Handle filename with or without .md extension
    if not filename.endswith(".md"):
        filename += ".md"
    
    file_path = vault / filename
    
    # Simple fuzzy check if not found directly
    if not file_path.exists():
        found = list(vault.rglob(filename))
        if found:
            file_path = found[0]
        else:
            return f"Error: Note '{filename}' not found."
    
    try:
        content = file_path.read_text(encoding="utf-8")
        
        if not header:
            return content
            
        # Header Extraction Logic
        # 1. Find the header line. Regex: ^#{1,6}\s+HeaderName (case insensitive for user friendliness?)
        # Let's try exact match first as Obsidian does, but maybe case insensitive for CLI ease.
        # User said: "matches exactly the heading in your note".
        # We will iterate lines to find the best match.
        
        lines = content.splitlines()
        start_idx = -1
        header_level = 0
        
        # Normalize header string for search
        target_header_clean = header.strip().lower()
        
        for i, line in enumerate(lines):
            match = re.match(r'^(#{1,6})\s+(.*)', line)
            if match:
                level = len(match.group(1))
                text = match.group(2).strip()
                
                if text.lower() == target_header_clean:
                    start_idx = i
                    header_level = level
                    break
        
        if start_idx == -1:
             return f"Error: Header '{header}' not found in '{filename}'."
             
        # 2. Extract until next header of same or higher (lower number) level
        extracted_lines = [lines[start_idx]] # Include the header itself
        for line in lines[start_idx+1:]:
            match = re.match(r'^(#{1,6})\s+', line)
            if match:
                current_level = len(match.group(1))
                if current_level <= header_level:
                    break
            extracted_lines.append(line)
            
        return "\n".join(extracted_lines)

    except Exception as e:
        return f"Error reading file: {e}"

def write_note(filename: str, content: str) -> str:
    """Creates or overwrites a note with the given content."""
    vault = _get_vault_path()
    if not filename.endswith(".md"):
        filename += ".md"
    
    file_path = vault / filename
    try:
        file_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {filename}"
    except Exception as e:
        return f"Error writing file: {e}"

def list_notes(limit: int = 20) -> List[str]:
    """Lists recent notes in the vault."""
    vault = _get_vault_path()
    files = sorted(vault.rglob("*.md"), key=os.path.getmtime, reverse=True)
    return [f.name for f in files[:limit]]

def fuzzy_find(filename: str) -> str:
    """Finds a file path by fuzzy matching the name."""
    vault = _get_vault_path()
    all_files = list(vault.rglob("*.md"))
    # Simple substring match for now, or use complex logic if needed
    matches = [f for f in all_files if filename.lower() in f.name.lower()]
    
    if not matches:
        return "No matches found."
    
    # Return top 5
    return "\n".join([str(f.relative_to(vault)) for f in matches[:5]])
