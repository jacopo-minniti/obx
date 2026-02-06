import difflib
from rich.console import Console
from rich.text import Text

console = Console()

class Editor:
    @staticmethod
    def generate_diff(original: str, modified: str, filename: str = "note.md") -> None:
        """
        Generates and prints a colored unified diff to the console.
        """
        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            original_lines, 
            modified_lines, 
            fromfile=f"Original {filename}", 
            tofile=f"Modified {filename}",
            lineterm=""
        )
        
        # Visualize with Rich
        for line in diff:
            if line.startswith("---") or line.startswith("+++"):
                console.print(Text(line.rstrip(), style="bold white"))
            elif line.startswith("@@"):
                console.print(Text(line.rstrip(), style="cyan"))
            elif line.startswith("+"):
                console.print(Text(line.rstrip(), style="bold green"))
            elif line.startswith("-"):
                console.print(Text(line.rstrip(), style="bold red strike"))
            else:
                console.print(Text(line.rstrip(), style="dim white"))

    @staticmethod
    def apply_insertion(original: str, context: str, content: str, mode: str = "after") -> str:
        """
        Inserts content relative to a context anchor.
        
        Args:
            original: Full text info
            context: Unique string to locate in original
            content: Information to insert
            mode: 'after' (default) or 'before'
        
        Returns:
            Modified string or raises ValueError if context not found/unique.
        """
        # Normalize for search (ignore leading/trailing whitespace specifics in matching?)
        # For robustness, we might need fuzzy matching, but let's try strict first.
        
        if context not in original:
            # Fallback: Try identifying unique line
            raise ValueError("Context anchor not found in original text.")
            
        if original.count(context) > 1:
            raise ValueError("Context anchor is not unique in original text.")
            
        # Perform insertion
        if mode == "after":
            return original.replace(context, context + "\n" + content + "\n")
        elif mode == "before":
            return original.replace(context, content + "\n" + context)
        
        return original
