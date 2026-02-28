import typer
import asyncio
from rich.panel import Panel
from rich.markdown import Markdown
import questionary
import urllib.parse
import subprocess
from pathlib import Path
from collections import defaultdict

from obx.utils.ui import (
    console,
    format_markdown,
    stream_agent_output,
    command_timer,
    log_model_usage,
    log_embedding_usage,
    log_tokens_generated,
)
from obx.cli.utils import ensure_configured
from obx.core.config import settings
from obx.utils.fs import resolve_note_path

def index_command(
    clear: bool = typer.Option(False, "--clear", help="Clear the existing index and re-index everything.")
):
    """Index the vault for search."""
    with command_timer():
        ensure_configured()
        log_embedding_usage(settings.embedding_provider, settings.embedding_model)
        console.print("[bold blue]Starting indexing process...[/bold blue]")

        try:
            with console.status("Initializing indexing engine..."):
                from obx.rag.engine import RAG
                rag = RAG()
            asyncio.run(rag.ingest(clear=clear))
        except Exception as e:
            console.print(f"[red]Indexing failed:[/red] {e}")

def search_command(
    topic: str,
    where: str = typer.Option("here", "--where", "-w", help="Output: 'here' (print) or note name/path to append to")
):
    """Hybrid search for notes relevant to a topic."""
    with command_timer():
        ensure_configured()
        log_embedding_usage(settings.embedding_provider, settings.embedding_model)
        console.print(f"[bold blue]Searching for:[/bold blue] {topic}...")
        
        try:
            with console.status("Initializing search engine..."):
                from obx.rag.engine import RAG
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
                    snippet_content = Markdown(format_markdown(text))
                    console.print(Panel(
                        snippet_content,
                        title=f"[dim]Score: {score:.2f}[/dim]",
                        border_style="dim white",
                        expand=False
                    ))

            # Handle --where output
            if where.lower() != "here":
                target = resolve_note_path(where)
                if target is None:
                    console.print(f"[red]Error:[/red] Note '{where}' not found in vault.")
                    return
                lines = [f"\n## Search results: {topic}", ""]
                for source, chunks in sorted_sources:
                    chunks.sort(key=lambda x: x['score'], reverse=True)
                    lines.append(f"### {source}")
                    for chunk in chunks[:3]:
                        score = chunk.get("score", 0)
                        text = chunk.get("text", "").strip()
                        lines.append(f"- Score: {score:.2f}")
                        if text:
                            lines.append("")
                            lines.append(text)
                            lines.append("")
                try:
                    existing = target.read_text(encoding="utf-8")
                    new_content = existing.rstrip() + "\n\n" + "\n".join(lines) + "\n"
                    target.write_text(new_content, encoding="utf-8")
                    console.print(f"[green]Added search results to {target.name}[/green]")
                except Exception as e:
                    console.print(f"[red]Error writing to {target}: {e}[/red]")

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

def ask_command(
    question: str,
    where: str = typer.Option("here", "--where", "-w", help="Output: 'here' (print) or note name/path to append to"),
    mode: str = typer.Option(None, "--mode", help="Force 'topic' mode to research the question instead of answering about a specific note.")
):
    """Ask a question and get answers based on vault content."""
    with command_timer():
        ensure_configured()
        log_model_usage("Model", settings.primary_model)
    
        # Determine Mode
        target = None
        vault = settings.vault_path
        forced_topic = mode == "topic"
        resolved_mode = "topic"
        
        # Logic to resolve valid note path if NOT forced to topic
        if not forced_topic:
            # 1. Exact path
            target_path = vault / question
            if not target_path.suffix: 
                target_path = target_path.with_suffix(".md")
                
            if target_path.exists():
                target = target_path
                resolved_mode = "note"
            else:
                # 2. Recursive exact match
                note_name = question if question.endswith(".md") else f"{question}.md"
                matches = list(vault.rglob(note_name))
                if matches:
                    target = matches[0]
                    resolved_mode = "note"

    # Print intent first
        if resolved_mode == "note":
            console.print(f"[bold blue]Asking about Note:[/bold blue] {target.name}")
        else:
            console.print(f"[bold blue]Answering Question:[/bold blue] {question}")

        async def run_stream():
            # Prepare the prompt
            if resolved_mode == "note":
                try:
                    content = target.read_text(encoding="utf-8")
                    prompt = (
                        f"Answer questions about the following note. "
                        f"Provide relevant information based on its content.\n"
                        f"IMPORTANT: Cite the most specific header from '{target.name}' using the format "
                        f"'[vault note: {target.name} > Header]'. If no header applies, use "
                        f"'[vault note: {target.name}]'.\n\n"
                        f"--- Note Content: {target.name} ---\n{content}"
                    )
                except Exception as e:
                    console.print(f"[red]Error reading note:[/red] {e}")
                    return
            else:
                prompt = (
                    f"Answer the question: '{question}' using the available search tools to find relevant notes in the vault. "
                    f"Provide a clear and direct answer based on the information found. "
                    f"IMPORTANT: You MUST cite your sources with the most specific headers when available "
                    f"(e.g., '[vault note: Note Name > Header]'). If no header is available, "
                    f"use '[vault note: Note Name]'. If you use web search, include clickable sources as "
                    f"'[web: Title](URL)'."
                )

            # Stream the response
            try:
                from obx.agents.ask import ask_agent
                output, usage = await stream_agent_output(ask_agent, prompt)
                log_tokens_generated(usage)
                # Handle --where output
                if where.lower() != "here":
                    write_target = resolve_note_path(where)
                    if write_target is None:
                        console.print(f"[red]Error:[/red] Note '{where}' not found in vault.")
                        return
                    if output:
                        try:
                            existing = write_target.read_text(encoding="utf-8")
                            new_content = existing.rstrip() + "\n\n" + output.strip() + "\n"
                            write_target.write_text(new_content, encoding="utf-8")
                            console.print(f"[green]Added answer to {write_target.name}[/green]")
                        except Exception as e:
                            console.print(f"[red]Error writing to {write_target}: {e}[/red]")
                
            except Exception as e:
                console.print(f"[red]Error answering question:[/red] {e}")

        asyncio.run(run_stream())
