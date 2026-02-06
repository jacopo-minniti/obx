import typer
import asyncio
from rich.panel import Panel
from rich.markdown import Markdown
from rich.live import Live
import questionary
import urllib.parse
import subprocess
from pathlib import Path
from collections import defaultdict

from obx.utils.ui import console, format_markdown
from obx.cli.utils import ensure_configured
from obx.core.config import settings
from obx.rag.engine import RAG
from obx.agents.explain import explain_agent

def index_command(
    clear: bool = typer.Option(False, "--clear", help="Clear the existing index and re-index everything.")
):
    """Index the vault for search."""
    ensure_configured()
    
    console.print("[bold blue]Starting indexing process...[/bold blue]")

    try:
        with console.status("Initializing indexing engine..."):
            rag = RAG()
        asyncio.run(rag.ingest(clear=clear))
    except Exception as e:
        console.print(f"[red]Indexing failed:[/red] {e}")

def search_command(topic: str):
    """Hybrid search for notes relevant to a topic."""
    ensure_configured()
    
    console.print(f"[bold blue]Searching for:[/bold blue] {topic}...")
    
    try:
        with console.status("Initializing search engine..."):
            rag = RAG()
            results = rag.search(topic, limit=15)
            
        if not results:
            console.print("[yellow]No results found.[/yellow]")
            return
            
        # Group by Source Note
        grouped = defaultdict(list)
        for r in results:
            source = r.get("source", "Unknown")
            grouped[source].append(r)
            
        # Sort notes by their best chunk's score
        sorted_sources = sorted(grouped.items(), key=lambda x: max(c['score'] for c in x[1]), reverse=True)
        
        # Display Results
        for source, chunks in sorted_sources:
            # Sort chunks by score
            chunks.sort(key=lambda x: x['score'], reverse=True)
            top_chunk = chunks[0]
            max_score = top_chunk['score']
            
            # Header
            console.print(f"\n[bold cyan underline]📄 {source}[/bold cyan underline] (Best Score: {max_score:.2f})")
            
            # Show top 2 chunks per file to avoid clutter
            for chunk in chunks[:2]:
                score = chunk.get('score', 0)
                text = chunk.get('text', '').strip()
                
                # Create a snippet panel
                snippet_content = Markdown(text)
                console.print(Panel(
                    snippet_content,
                    title=f"[dim]Score: {score:.2f}[/dim]",
                    border_style="dim white",
                    expand=False
                ))

        # Interactivity: Open a note
        console.print()
        choices = [s[0] for s in sorted_sources] # Source filenames
        choices.append("Cancel")
        
        answer = questionary.select(
            "Select a note to open in Obsidian:",
            choices=choices,
            pointer="❯",
        ).ask()
        
        if answer and answer != "Cancel":
            # Find the path for the selected source
            selected_path = None
            for r in results:
                if r.get("source") == answer:
                    selected_path = Path(r.get("path"))
                    break
            
            if selected_path and selected_path.exists():
                console.print(f"Opening {answer}...")
                vault = settings.vault_path
                vault_name = urllib.parse.quote(vault.name)
                relative_path = selected_path.relative_to(vault)
                file_path_encoded = urllib.parse.quote(str(relative_path))
                
                uri = f"obsidian://open?vault={vault_name}&file={file_path_encoded}"
                subprocess.run(["open", uri])
            else:
                console.print(f"[red]Could not find file path for {answer}[/red]")
        else:
            console.print("[dim]Exiting search.[/dim]")

    except Exception as e:
        console.print(f"[red]Search failed:[/red] {e}")

def explain_command(
    topic: str,
    where: str = typer.Option(None, "--where", help="Force 'topic' mode to research the topic instead of explaining a specific note.")
):
    """Explain a topic or a specific note based on vault content."""
    ensure_configured()
    
    # Determine Mode
    mode = "topic"
    target = None
    vault = settings.vault_path
    
    # Logic to resolve valid note path if NOT forced to topic
    if where != "topic":
        # 1. Exact path
        target_path = vault / topic
        if not target_path.suffix: 
            target_path = target_path.with_suffix(".md")
            
        if target_path.exists():
            target = target_path
            mode = "note"
        else:
            # 2. Recursive exact match
            note_name = topic if topic.endswith(".md") else f"{topic}.md"
            matches = list(vault.rglob(note_name))
            if matches:
                 target = matches[0]
                 mode = "note"
            else:
                 pass

    # Print intent first
    if mode == "note":
        console.print(f"[bold blue]Explaining Note:[/bold blue] {target.name}")
    else:
        console.print(f"[bold blue]Researching Topic:[/bold blue] {topic}")

    async def run_stream():
        full_response = ""
        
        # Prepare the prompt
        if mode == "note":
            try:
                content = target.read_text(encoding="utf-8")
                prompt = (
                    f"Explain the following note to the user. "
                    f"Summarize its key points and context.\n"
                    f"IMPORTANT: Cite the note '{target.name}' as the source in your response.\n\n"
                    f"--- Note Content: {target.name} ---\n{content}"
                )
            except Exception as e:
                console.print(f"[red]Error reading note:[/red] {e}")
                return
        else:
            prompt = (
                f"Explain the topic '{topic}' using the available search tools to find relevant notes in the vault. "
                f"Identify key information and Synthesize it. "
                f"IMPORTANT: You MUST cite your sources (e.g., '...[Source: Note Name]')."
            )

        # Stream the response
        try:
            # We use rich.Live for nice markdown formatting during generation.
            async with explain_agent.run_stream(prompt) as result:
                with Live(Markdown(""), refresh_per_second=12, console=console) as live:
                    async for snapshot in result.stream():
                        live.update(Markdown(format_markdown(snapshot)))
            
        except Exception as e:
            console.print(f"[red]Error during explanation:[/red] {e}")

    asyncio.run(run_stream())
