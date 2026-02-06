from rich.console import Console
from rich.theme import Theme
import re
import urllib.parse
from obx.core.config import settings

# Custom theme for better markdown aesthetics vs readability
obx_theme = Theme({
    "markdown.h1": "bold cyan underline",
    "markdown.h2": "bold bright_blue",
    "markdown.h3": "bold blue",
    "markdown.link": "bright_blue underline",
    "markdown.code_block": "white on #1e1e1e",
    "markdown.code": "bold yellow", 
    "markdown.item": "white",       # Bullets
    "markdown.list": "white",       # List content
    "markdown.block_quote": "dim white",
})

console = Console(theme=obx_theme)

def format_markdown(text: str) -> str:
    """Pre-processes markdown to make LaTeX math look nicer and highlight sources."""
    if not text:
        return ""
    
    # 0. Highlight Sources: [Source: Note Name] -> Markdown Link to open in Obsidian
    def replace_source(match):
        note_name = match.group(1)
        if settings.vault_path:
            vault_name = urllib.parse.quote(settings.vault_path.name)
            # Encode the file path/name
            encoded_file = urllib.parse.quote(note_name)
            uri = f"obsidian://open?vault={vault_name}&file={encoded_file}"
            # Return a markdown link: [Source: Note Name](uri)
            return f"[[Source: {note_name}]]({uri})"
        return match.group(0)

    text = re.sub(
        r'\[Source: (.*?)\]', 
        replace_source, 
        text
    )

    # 1. Block Math: $$ ... $$ -> ```latex ... ```
    text = re.sub(
        r'\$\$(.*?)\$\$', 
        r'```latex\n\1\n```', 
        text, 
        flags=re.DOTALL
    )
    
    # 2. Inline Math: $...$ -> `$ ... $`
    text = re.sub(
        r'(?<!\\)\$(?!\s)([^$\n]+?)(?<!\s)(?<!\\)\$', 
        r'`$\1$`', 
        text
    )
    
    return text
