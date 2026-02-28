import difflib
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from typing import List, Tuple, Optional

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
        if context not in original:
            raise ValueError("Context anchor not found in original text.")
            
        if original.count(context) > 1:
            raise ValueError("Context anchor is not unique in original text.")
            
        # Perform insertion
        if mode == "after":
            return original.replace(context, context + "\n" + content + "\n")
        elif mode == "before":
            return original.replace(context, content + "\n" + context)
        
        return original

    @staticmethod
    def apply_multi_insertions(original: str, proposals: List[dict]) -> str:
        """
        Apply multiple insertions, processing from bottom to top to preserve line positions.
        
        Each proposal should have: target_context, content_to_insert, insertion_mode
        """
        # Sort by position in original (reversed to process from end)
        def get_position(p):
            ctx = p.get("target_context", "")
            try:
                return original.index(ctx)
            except ValueError:
                return -1
        
        sorted_proposals = sorted(proposals, key=get_position, reverse=True)
        
        result = original
        for p in sorted_proposals:
            ctx = p.get("target_context", "")
            content = p.get("content_to_insert", "")
            mode = p.get("insertion_mode", "after")
            
            if ctx not in result:
                continue  # Skip if anchor not found
            if result.count(ctx) > 1:
                continue  # Skip ambiguous anchors
            
            if mode == "after":
                result = result.replace(ctx, ctx + "\n\n" + content)
            else:
                result = result.replace(ctx, content + "\n\n" + ctx)
        
        return result
    
    @staticmethod
    def display_multi_diff(
        original: str, 
        proposals: List[dict], 
        filename: str = "note.md"
    ) -> List[Tuple[int, dict, str]]:
        """
        Display each proposal as a numbered diff.
        
        Returns list of (index, proposal, preview_content) for later approval.
        """
        previews = []
        
        for i, p in enumerate(proposals, 1):
            ctx = p.get("target_context", "")[:60]
            content_preview = p.get("content_to_insert", "")[:100]
            mode = p.get("insertion_mode", "after")
            reasoning = p.get("reasoning", "")
            
            console.print(f"\n[bold cyan]─── Proposal {i}/{len(proposals)} ───[/bold cyan]")
            if reasoning:
                console.print(f"[dim]{reasoning}[/dim]")
            console.print(f"Mode: [yellow]{mode}[/yellow] anchor: [dim]{ctx}...[/dim]")
            
            # Create mini-diff for this single insertion
            try:
                single_result = Editor.apply_insertion(
                    original, 
                    p.get("target_context", ""), 
                    p.get("content_to_insert", ""),
                    mode
                )
                Editor.generate_diff(original, single_result, filename)
                previews.append((i, p, single_result))
            except ValueError as e:
                console.print(f"[red]Error: {e}[/red]")
                previews.append((i, p, None))
        
        return previews

