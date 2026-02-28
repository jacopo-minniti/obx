import typer
import subprocess
import urllib.parse
import json
from pathlib import Path
from typing import Optional
from questionary import Style
import questionary
from obx.utils.ui import (
    console,
    render_markdown,
    command_timer,
    log_model_usage,
    log_embedding_usage,
    extract_usage,
    log_tokens_generated,
)
from obx.cli.utils import ensure_configured
from obx.core.config import settings
from obx.utils.fs import read_note, write_note, fuzzy_find
from obx.utils.editor import Editor
from obx.agents.editor import editor_agent, EditProposal
from obx.rag.engine import RAG

def open_command(
    note: str,
    header: Optional[str] = typer.Option(None, "--header", help="Open note at specific header.")
):
    """Open a note in Obsidian, optionally at a section."""
    with command_timer():
        ensure_configured()
        vault = settings.vault_path
        target = None

        # 1. Try exact path match (if user provided a path)
        potential_path = vault / note
        if not potential_path.suffix:
            potential_path = potential_path.with_suffix(".md")
        
        if potential_path.exists():
            target = potential_path
        
        # 2. recursive exact name match
        if not target:
            note_name = note if note.endswith(".md") else f"{note}.md"
            exact_matches = list(vault.rglob(note_name))
            if exact_matches:
                target = exact_matches[0] # Pick first exact match if duplicates exist
                
        # 3. Fuzzy match (substring)
        if not target:
            console.print(f"[yellow]Exact match for '{note}' not found. Searching...[/yellow]")
            all_files = list(vault.rglob("*.md"))
            fuzzy_matches = [f for f in all_files if note.lower() in f.name.lower()]
            
            if fuzzy_matches:
                # Take top 3
                top_matches = fuzzy_matches[:3]

                # Prepare choices with intelligent labeling
                choices = []
                display_map = {}
                
                match_names = [m.name for m in top_matches]
                
                for m in top_matches:
                    # If multiple matches have the same name, show parent folder to distinguish
                    if match_names.count(m.name) > 1:
                        label = f"{m.name} ({m.relative_to(vault).parent})"
                    else:
                        label = m.name
                    
                    choices.append(label)
                    display_map[label] = m
                
                choices.append("Cancel")
                
                # Custom style for a polished look
                custom_style = Style([
                    ('qmark', 'fg:#36cdc4 bold'),       # Cyan-ish
                    ('question', 'bold'),
                    ('pointer', 'fg:#36cdc4 bold'),     # Pointer color
                    ('highlighted', 'fg:#36cdc4 bold'), # Selected item color
                    ('answer', 'fg:white bold'),        # Use white for answers, not cyan
                ])

                answer = questionary.select(
                    f"No exact match for '{note}'. Did you mean:",
                    choices=choices,
                    style=custom_style,
                    pointer="❯",
                    instruction=""
                ).ask()
                
                if answer and answer != "Cancel":
                    target = display_map[answer]
                else:
                    console.print("[yellow]Selection cancelled.[/yellow]")
                    return

        if target:
            console.print(f"Opening {target.name}...")
            
            vault_name = urllib.parse.quote(vault.name)
            # Get path relative to vault root
            relative_path = target.relative_to(vault)
            file_param = str(relative_path)
            if header:
                file_param = f"{file_param}#{header}"
            file_path = urllib.parse.quote(file_param, safe="/")
            
            uri = f"obsidian://open?vault={vault_name}&file={file_path}"
            
            subprocess.run(["open", uri])
        else:
            console.print(f"[red]Note '{note}' not found.[/red]")

def read_command(
    note: str,
    header: Optional[str] = typer.Option(None, "--header", help="Read only a specific section.")
):
    """Read a note and display in terminal."""
    with command_timer():
        ensure_configured()
        content = read_note(note, header=header)
        if content.startswith("Error"):
            console.print(f"[red]{content}[/red]")
        else:
            render_markdown(content)

def insert_command(
    content: str = typer.Argument(..., help="Content to insert into a note"),
    where: Optional[str] = typer.Option(None, "--where", "-w", help="Target note name. If omitted, finds best match.")
):
    """Insert content into a note with smart placement and diff review."""
    with command_timer():
        ensure_configured()
        log_model_usage("Model", settings.primary_model)

        # 1. Resolve Target Note
        target_path = None
        
        if where:
            # User specified note
            potential = settings.vault_path / where
            if not potential.suffix:
                potential = potential.with_suffix(".md")
            
            if potential.exists():
                target_path = potential
            else:
                # Fuzzy find
                res = fuzzy_find(where)
                if "No matches" not in res:
                    match = res.split('\n')[0]
                    target_path = settings.vault_path / match
        else:
            # Auto-discover using semantic search
            log_embedding_usage(settings.embedding_provider, settings.embedding_model)
            console.print("[dim]No note specified. Searching vault for best match...[/dim]")
            # We need the RAG engine
            try:
                rag = RAG()
                # Search for the content itself to find related context
                results = rag.search(content, limit=1)
                if results:
                    best = results[0]
                    source = best.get('source')
                    score = best.get('score', 0)
                    console.print(f"[green]Found match:[/green] {source} (Score: {score:.2f})")
                    
                    # Resolve path
                    res = fuzzy_find(source.replace(".md", "")) # remove ext to be safe for fuzzy
                    if "No matches" not in res:
                        match = res.split('\n')[0]
                        target_path = settings.vault_path / match
                else:
                    console.print("[yellow]No relevant note found to insert into.[/yellow]")
                    if typer.confirm("Create a new note instead?"):
                        new_name = typer.prompt("New note name")
                        write_note(new_name, content)
                        console.print(f"[green]Created {new_name}[/green]")
                        return
                    else:
                        return
            except Exception as e:
                console.print(f"[red]Search failed:[/red] {e}")
                return

        if not target_path or not target_path.exists():
            console.print(f"[red]Target note could not be resolved.[/red]")
            return
            
        console.print(f"[bold blue]Targeting:[/bold blue] {target_path.name}")
        
        # 2. Read Note Content
        original_content = target_path.read_text(encoding="utf-8")
        
        # 3. Call Editor Agent
        with console.status("Analyzing insertion point..."):
            prompt = (
                f"--- Target Note: {target_path.name} ---\n{original_content}\n\n"
                f"--- Content to Insert ---\n{content}"
            )
            
            try:
                # Pydantic AI run sync (JSON string)
                result = editor_agent.run_sync(prompt)
                log_tokens_generated(extract_usage(getattr(result, "usage", None)))
                # Parse manually
                clean_json = result.output.strip()
                if clean_json.startswith("```"):
                    clean_json = clean_json.split("\n", 1)[1]
                    if clean_json.endswith("```"):
                        clean_json = clean_json.rsplit("\n", 1)[0]
                
                data = json.loads(clean_json)
                proposal = EditProposal(**data)
            except Exception as e:
                console.print(f"[red]Agent failed:[/red] {e}")
                return

        # 4. Generate & Visualize Diff
        try:
            new_content = Editor.apply_insertion(
                original_content, 
                proposal.target_context, 
                proposal.content_to_insert, 
                proposal.insertion_mode
            )
            
            console.print(f"\n[bold]Proposed change ({proposal.reasoning}):[/bold]")
            Editor.generate_diff(original_content, new_content, filename=target_path.name)
            
            # 5. Confirm & Apply
            console.print()
            if typer.confirm("Apply this change?"):
                target_path.write_text(new_content, encoding="utf-8")
                console.print(f"[green]Successfully updated {target_path.name}[/green]")
            else:
                console.print("[yellow]Operation cancelled.[/yellow]")
                
        except ValueError as e:
            console.print(f"[red]Error applying change:[/red] {e}")
            console.print("[dim]The agent might have selected an ambiguous anchor. Try again or edit manually.[/dim]")
