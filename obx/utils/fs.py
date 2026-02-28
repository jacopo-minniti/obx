import os
import re
from pathlib import Path
from typing import List, Optional
from datetime import datetime
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

def list_note_headers(filename: str) -> str:
    """List markdown headers from a note with their levels."""
    vault = _get_vault_path()
    if not filename.endswith(".md"):
        filename += ".md"
    file_path = vault / filename

    if not file_path.exists():
        found = list(vault.rglob(filename))
        if found:
            file_path = found[0]
        else:
            return f"Error: Note '{filename}' not found."

    try:
        content = file_path.read_text(encoding="utf-8")
        headers = []
        for line in content.splitlines():
            match = re.match(r'^(#{1,6})\s+(.*)', line)
            if match:
                level = len(match.group(1))
                text = match.group(2).strip()
                headers.append(f"{level} {text}")
        if not headers:
            return "No headers found."
        return "\n".join(headers)
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

def write_generated_note(content: str, filename: Optional[str] = None) -> str:
    """Write a generated note into the configured output directory."""
    vault = _get_vault_path()
    if not settings.output_dir:
        return "Error: Output directory not configured."

    out_dir = vault / settings.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"study-guide-{timestamp}.md"

    if not filename.endswith(".md"):
        filename += ".md"

    file_path = out_dir / filename
    try:
        tagged_content = "---\ntags: [obx]\n---\n\n" + content.strip() + "\n"
        file_path.write_text(tagged_content, encoding="utf-8")
        return f"Successfully wrote to {file_path}"
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


# --- YAML Frontmatter Helpers for Learning Scores ---

def _parse_yaml_frontmatter(content: str) -> tuple[dict, str, int, int]:
    """
    Parse YAML frontmatter from markdown content.
    
    Returns (yaml_dict, body, frontmatter_start, frontmatter_end).
    If no frontmatter, returns ({}, content, -1, -1).
    """
    import yaml
    
    if not content.startswith("---"):
        return {}, content, -1, -1
    
    # Find the closing ---
    end_match = re.search(r'\n---\s*\n', content[3:])
    if not end_match:
        return {}, content, -1, -1
    
    frontmatter_end = 3 + end_match.end()
    frontmatter_text = content[3:3 + end_match.start()]
    
    try:
        yaml_data = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        yaml_data = {}
    
    body = content[frontmatter_end:]
    return yaml_data, body, 0, frontmatter_end


def _serialize_yaml_frontmatter(yaml_dict: dict) -> str:
    """Serialize a dict to YAML frontmatter format."""
    import yaml
    
    if not yaml_dict:
        return ""
    
    yaml_str = yaml.dump(yaml_dict, default_flow_style=False, allow_unicode=True)
    return f"---\n{yaml_str}---\n\n"


def get_note_yaml(content: str) -> dict:
    """Get the YAML frontmatter dict from note content."""
    yaml_data, _, _, _ = _parse_yaml_frontmatter(content)
    return yaml_data


def update_note_yaml(content: str, updates: dict) -> str:
    """
    Update YAML frontmatter with new values, preserving existing.
    
    Creates frontmatter if it doesn't exist.
    """
    yaml_data, body, start, end = _parse_yaml_frontmatter(content)
    
    # Merge updates
    yaml_data.update(updates)
    
    # Rebuild content
    new_frontmatter = _serialize_yaml_frontmatter(yaml_data)
    
    if start == -1:
        # No existing frontmatter - add it
        return new_frontmatter + content
    else:
        # Replace existing frontmatter
        return new_frontmatter + body


def get_learning_scores(filename: str) -> dict:
    """
    Get learning scores from a note's YAML frontmatter.
    
    Returns {"memory": float, "exercise": float}.
    """
    vault = _get_vault_path()
    if not filename.endswith(".md"):
        filename += ".md"
    
    file_path = vault / filename
    if not file_path.exists():
        found = list(vault.rglob(filename))
        if found:
            file_path = found[0]
        else:
            return {"memory": 0.0, "exercise": 0.0}
    
    try:
        content = file_path.read_text(encoding="utf-8")
        yaml_data = get_note_yaml(content)
        return {
            "memory": float(yaml_data.get("memory", 0.0)),
            "exercise": float(yaml_data.get("exercise", 0.0)),
        }
    except Exception:
        return {"memory": 0.0, "exercise": 0.0}


def update_learning_scores(filename: str, memory: float, exercise: float) -> str:
    """
    Update learning scores in a note's YAML frontmatter.
    
    Returns success/error message.
    """
    vault = _get_vault_path()
    if not filename.endswith(".md"):
        filename += ".md"
    
    file_path = vault / filename
    if not file_path.exists():
        found = list(vault.rglob(filename))
        if found:
            file_path = found[0]
        else:
            return f"Error: Note '{filename}' not found."
    
    try:
        content = file_path.read_text(encoding="utf-8")
        updated = update_note_yaml(content, {
            "memory": round(memory, 2),
            "exercise": round(exercise, 2),
        })
        file_path.write_text(updated, encoding="utf-8")
        return f"Updated learning scores in {file_path.name}"
    except Exception as e:
        return f"Error updating scores: {e}"


def resolve_note_path(name: str) -> Optional[Path]:
    """
    Resolve a name to a note path using fuzzy matching.
    
    Returns the Path if found, None otherwise.
    """
    vault = _get_vault_path()
    
    # Try exact path
    potential = vault / name
    if not potential.suffix:
        potential = potential.with_suffix(".md")
    if potential.exists():
        return potential
    
    # Try recursive exact match
    note_name = name if name.endswith(".md") else f"{name}.md"
    exact_matches = list(vault.rglob(note_name))
    if exact_matches:
        return exact_matches[0]
    
    # Fuzzy match
    all_files = list(vault.rglob("*.md"))
    matches = [f for f in all_files if name.lower() in f.name.lower()]
    if matches:
        # Return best match (shortest name that contains the query)
        return min(matches, key=lambda f: len(f.name))
    
    return None


def list_vault_hierarchy() -> str:
    """Returns a tree-like string of the vault's folder structure (subdirectories only)."""
    try:
        vault = _get_vault_path()
        result = [f"Vault: {vault.name}"]
        
        def walk(path: Path, indent: str = ""):
            # Get immediate subdirectories, excluding hidden/ignored ones
            try:
                subdirs = sorted([
                    d for d in path.iterdir() 
                    if d.is_dir() 
                    and not d.name.startswith(('.', '_'))
                    and d.name not in settings.exclude_folders
                ])
                for i, d in enumerate(subdirs):
                    is_last = (i == len(subdirs) - 1)
                    marker = "└── " if is_last else "├── "
                    result.append(f"{indent}{marker}{d.name}")
                    new_indent = indent + ("    " if is_last else "│   ")
                    walk(d, new_indent)
            except PermissionError:
                result.append(f"{indent}└── [Permission Denied]")
                
        walk(vault)
        return "\n".join(result)
    except Exception as e:
        return f"Error listing vault hierarchy: {e}"


def list_folder_contents(folder_path: str = ".") -> str:
    """
    Lists all files in a specific folder (non-recursive).
    Includes the first 100 characters of each markdown note as a snippet.
    """
    try:
        base_vault = _get_vault_path()
        
        # Handle relative path from vault root
        if folder_path == "." or not folder_path:
            target_dir = base_vault
        else:
            target_dir = (base_vault / folder_path).resolve()
        
        # Security check: ensure target_dir is within base_vault
        if not str(target_dir).startswith(str(base_vault.resolve())):
            return "Error: Path is outside the vault."
            
        if not target_dir.exists() or not target_dir.is_dir():
            return f"Error: Folder '{folder_path}' not found."
            
        files = sorted([f for f in target_dir.iterdir() if f.is_file() and not f.name.startswith('.')])
        if not files:
            return f"No files found in '{folder_path}'."
            
        result = []
        for f in files:
            if f.suffix == ".md":
                try:
                    content = f.read_text(encoding="utf-8")
                    # Get first 100 non-YAML chars
                    _, body, _, _ = _parse_yaml_frontmatter(content)
                    snippet = body[:100].replace("\n", " ").strip()
                    result.append(f"- {f.name}: {snippet}...")
                except Exception:
                    result.append(f"- {f.name}: [Error reading content]")
            else:
                result.append(f"- {f.name}")
                
        return f"Contents of '{folder_path}':\n" + "\n".join(result)
    except Exception as e:
        return f"Error listing folder contents: {e}"

