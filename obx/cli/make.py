"""CLI commands for creating learning content (guides, notes, flashcards, exercises)."""

import typer
import asyncio
import questionary
import json
import sys
import re
from typing import List, Optional, Union
from pathlib import Path
from pydantic_ai import BinaryContent


from obx.utils.ui import (
    console,
    stream_agent_output,
    command_timer,
    log_model_usage,
    log_tokens_generated,
    extract_usage,
)
from obx.cli.utils import ensure_configured, update_note_scores
from obx.core.learning_parser import get_all_learning_items
from obx.core.config import settings
from obx.utils.fs import resolve_note_path, read_note, update_note_yaml, get_note_yaml
from obx.utils.editor import Editor


make = typer.Typer(help="Tools for creating content (guides, flashcards, notes, exercises).")


def _resolve_where(where: str) -> tuple[str, Optional[Path]]:
    """
    Resolve the --where argument.
    
    Returns:
        ("here", None) if output should be printed
        ("note", Path) if output should be appended to a note
    
    Raises:
        typer.Exit if note not found
    """
    if where.lower() == "here":
        return "here", None
    
    # Try to resolve as a note path
    target = resolve_note_path(where)
    if target is None:
        console.print(f"[red]Error:[/red] Note '{where}' not found in vault.")
        raise typer.Exit(1)
    
    return "note", target


def _sanitize_filename(topic: str) -> str:
    """
    Sanitize a topic string to create a valid filename.
    
    Returns:
        Sanitized filename with .md extension
    """
    # Remove invalid filename characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '', topic)
    # Replace multiple spaces with single space
    sanitized = re.sub(r'\s+', ' ', sanitized)
    # Strip leading/trailing whitespace
    sanitized = sanitized.strip()
    # Ensure we have something
    if not sanitized:
        sanitized = "Untitled"
    # Add .md extension if not present
    if not sanitized.endswith('.md'):
        sanitized += '.md'
    return sanitized


def _determine_note_path(topic: str, where: Optional[str]) -> tuple[str, Optional[Path]]:
    """
    Determine where to create/write a note.
    
    Args:
        topic: The topic name
        where: User-specified location (None, "here", or note name/path)
    
    Returns:
        (mode, target_path) where mode is "here" or "note"
    """
    if where and where.lower() == "here":
        return "here", None
    
    if where:
        # User specified a note name/path
        target = resolve_note_path(where)
        if target:
            # Existing note - append to it
            return "note", target
        else:
            # Note doesn't exist - create it
            vault = settings.vault_path
            if settings.output_dir:
                out_dir = vault / settings.output_dir
                out_dir.mkdir(parents=True, exist_ok=True)
                target = out_dir / _sanitize_filename(where)
            else:
                target = vault / _sanitize_filename(where)
            return "note", target
    
    # Default: auto-create note from topic name
    vault = settings.vault_path
    if settings.output_dir:
        out_dir = vault / settings.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / _sanitize_filename(topic)
    else:
        target = vault / _sanitize_filename(topic)
    
    return "note", target


def _gather_sources(
    topic: str,
    extra_sources: Optional[List[str]] = None,
    include_topic_note: bool = True,
) -> tuple[str, str, List[Path]]:
    """
    Gather all sources for a command.
    
    Args:
        topic: The primary topic/note name
        extra_sources: Additional sources (PDFs, URLs, other notes)
        include_topic_note: Whether to include the topic note content
    
    Returns:
        (topic_content, sources_content_block, pdf_paths)
        where sources_content_block contains text sources and pdf_paths contains PDF files to pass as binary
    """
    topic_content = ""
    sources_parts = []
    pdf_paths = []
    
    # Try to resolve topic as a note
    topic_path = resolve_note_path(topic)
    if topic_path and include_topic_note:
        topic_content = topic_path.read_text(encoding="utf-8")
        sources_parts.append(f"### Source: {topic_path.name}\n{topic_content}\n")
    
    # Process extra sources - read their actual content
    if extra_sources:
        for src in extra_sources:
            # Split space-separated paths if present
            paths_to_process = []
            if ' ' in src and not src.startswith('http'):
                # Split on spaces (supports quoted paths with spaces)
                import shlex
                try:
                    paths_to_process = shlex.split(src)
                except ValueError:
                    # If shlex fails, treat as single source
                    paths_to_process = [src]
            else:
                paths_to_process = [src]
            
            # Read each path
            for path_str in paths_to_process:
                path = Path(path_str).expanduser().resolve()
                
                if not path.exists():
                    console.print(f"[yellow]Warning: Source file not found: {path_str}[/yellow]")
                    continue
                
                try:
                    # Read based on file type
                    if path.suffix.lower() == '.pdf':
                        # Add PDF path to be passed as binary to the model
                        pdf_paths.append(path)
                        sources_parts.append(f"### Source: {path.name} (PDF - attached)\n")
                    
                    elif path.suffix.lower() in ['.md', '.txt']:
                        # Read markdown or text file
                        content = path.read_text(encoding='utf-8')
                        sources_parts.append(f"### Source: {path.name}\n{content}\n")
                    
                    else:
                        console.print(f"[yellow]Warning: Unsupported file type: {path.name}[/yellow]")
                
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not read {path.name}: {e}[/yellow]")
    
    # Combine all sources into a single block
    sources_content = "\n\n".join(sources_parts) if sources_parts else ""
    
    return topic_content, sources_content, pdf_paths


def _prepare_message_with_pdfs(prompt: str, pdf_paths: List[Path]) -> Union[str, List[Union[str, BinaryContent]]]:
    """
    Prepare a message for an agent, including PDFs as binary attachments if present.
    
    Args:
        prompt: The text prompt
        pdf_paths: List of PDF file paths
        
    Returns:
        Either the prompt string (if no PDFs), or a list containing the prompt + BinaryContent objects
    """
    if not pdf_paths:
        return prompt
    
    # Build message with PDFs as binary attachments
    message_parts: List[Union[str, BinaryContent]] = [prompt]
    
    for pdf_path in pdf_paths:
        try:
            with open(pdf_path, 'rb') as f:
                pdf_data = f.read()
            
            binary_content = BinaryContent(
                data=pdf_data,
                media_type='application/pdf'
            )
            message_parts.append(binary_content)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not read PDF {pdf_path.name}: {e}[/yellow]")
    
    return message_parts




async def _insert_with_approval(
    target_path: Path,
    content_type: str,
    generated_content: str,
    topic_content: str,
) -> bool:
    """
    Use insert_learning_agent to place content organically and get user approval.
    This is kept for future use with other commands.
    
    Returns True if changes were applied.
    """
    # Ask agent to propose insertions
    prompt = (
        f"--- Target Note: {target_path.name} ---\n{topic_content}\n\n"
        f"--- {content_type.title()} to Insert ---\n{generated_content}"
    )
    
    with console.status(f"Planning {content_type} placement..."):
        try:
            from obx.agents.editor import insert_learning_agent
            result = await insert_learning_agent.run(prompt)
            log_tokens_generated(extract_usage(getattr(result, "usage", None)))
            
            # Parse JSON response
            clean_json = result.output.strip()
            if clean_json.startswith("```"):
                clean_json = clean_json.split("\n", 1)[1]
                if clean_json.endswith("```"):
                    clean_json = clean_json.rsplit("\n", 1)[0]
            
            data = json.loads(clean_json)
            proposals = data.get("proposals", [])
            
        except Exception as e:
            console.print(f"[red]Agent failed:[/red] {e}")
            # Fallback: append at end
            if await questionary.confirm("Append content at end of note instead?").ask_async():
                existing = target_path.read_text(encoding="utf-8")
                new_content = existing.rstrip() + "\n\n" + generated_content.strip() + "\n"
                target_path.write_text(new_content, encoding="utf-8")
                console.print(f"[green]Added {content_type} to {target_path.name}[/green]")
                return True
            return False
    
    if not proposals:
        console.print("[yellow]No insertion proposals generated.[/yellow]")
        return False
    
    # Display all diffs
    original = topic_content
    previews = Editor.display_multi_diff(original, proposals, target_path.name)
    
    choice = await questionary.select(
        "Choice:",
        choices=[
            {"name": "Apply all proposals", "value": "a"},
            {"name": "Select individually", "value": "s"},
            {"name": "Reject all", "value": "r"},
        ],
        default="a"
    ).ask_async()
    
    if choice == "r":
        console.print("[yellow]All proposals rejected.[/yellow]")
        return False
    
    approved_proposals = []
    
    if choice == "s":
        # Individual selection
        for idx, proposal, preview in previews:
            if preview is None:
                continue
            if await questionary.confirm(f"Apply proposal {idx}?").ask_async():
                approved_proposals.append(proposal)
    else:
        # Apply all valid proposals
        approved_proposals = [p for (_, p, preview) in previews if preview is not None]
    
    if not approved_proposals:
        console.print("[yellow]No proposals approved.[/yellow]")
        return False
    
    # Apply approved proposals
    try:
        proposals_dicts = [
            {
                "target_context": p.get("target_context") if isinstance(p, dict) else p.target_context,
                "content_to_insert": p.get("content_to_insert") if isinstance(p, dict) else p.content_to_insert,
                "insertion_mode": p.get("insertion_mode", "after") if isinstance(p, dict) else p.insertion_mode,
            }
            for p in approved_proposals
        ]
        new_content = Editor.apply_multi_insertions(original, proposals_dicts)
        target_path.write_text(new_content, encoding="utf-8")
        console.print(f"[green]Applied {len(approved_proposals)} changes to {target_path.name}[/green]")
        return True
    except Exception as e:
        console.print(f"[red]Error applying changes:[/red] {e}")
        return False


async def _append_at_end_with_diff(
    target_path: Path,
    content_type: str,
    generated_content: str,
    original_content: str,
    section_header: str = "## Flashcards"
) -> bool:
    """
    Append content at the end of a note under a section header.
    Shows a diff preview and asks for approval before applying.
    
    Returns True if changes were applied.
    """
    # Strip any duplicate header from agent output
    content_to_add = generated_content.strip()
    
    # Remove common header variations the agent might include
    if section_header:
        header_variations = [
            section_header,
            section_header.replace("## ", "# "),
            section_header.replace("## ", "### "),
            section_header + "\n",
        ]
        for header in header_variations:
            if content_to_add.startswith(header):
                content_to_add = content_to_add[len(header):].lstrip()
    
    # Check if note already has this section
    if section_header and section_header in original_content:
        # Append to existing section (just add content)
        new_content = original_content.rstrip() + "\n\n" + content_to_add + "\n"
    elif section_header:
        # Create new section
        new_section = f"\n{section_header}\n\n{content_to_add}\n"
        new_content = original_content.rstrip() + "\n" + new_section
    else:
        # No section header (e.g. for full note content)
        new_content = original_content.rstrip() + "\n\n" + content_to_add + "\n"
    
    # Show diff
    console.print(f"\n[bold cyan]── Proposed Changes ──[/bold cyan]")
    Editor.generate_diff(original_content, new_content, target_path.name)
    
    # Ask for approval
    console.print()
    if await questionary.confirm("Apply these changes?", default=True).ask_async():
        # Recalculate scores with the new content
        flashcards, exercises = get_all_learning_items(new_content)
        final_content = update_note_scores(target_path, {
            'flashcards': flashcards,
            'exercises': exercises
        }, new_content)
        
        target_path.write_text(final_content, encoding="utf-8")
        console.print(f"[green]Added {content_type} to {target_path.name}[/green]")
        return True
    else:
        console.print("[yellow]Changes rejected.[/yellow]")
        return False


@make.command()
def guide(
    topic: str = typer.Argument(..., help="Topic or note name to create a guide for"),
    sources: Optional[List[str]] = typer.Option(None, "--source", "-s", help="Additional sources (PDFs, URLs, notes)"),
    focus: Optional[str] = typer.Option(None, "--focus", "-f", help="Specific topic to focus the guide on."),
    where: str = typer.Option("here", "--where", "-w", help="Output: 'here' (print) or note name/path to append to")
):
    """Generate a study guide for a topic or note."""
    with command_timer():
        ensure_configured()
        log_model_usage("Model", settings.primary_model)
        
        mode, target = _resolve_where(where)
        topic_content, sources_content, pdf_paths = _gather_sources(topic, sources)

    
        prompt = f"Create a study guide for: {topic}\n\n"
        if sources_content:
            prompt += f"--- Source Materials ---\n{sources_content}\n---\n\n"
        prompt += (
            "If exercises are explicitly present in the sources, reference them by number/name and source, "
            "prioritize them, and explain the order. If no exercises exist, create targeted exercises.\n"
        )
        if focus:
            prompt += f"Focus strictly on: {focus}\n"
        
        console.print(f"[bold blue]Generating Study Guide for '{topic}'...[/bold blue]")
    
        async def run_stream():
            try:
                from obx.agents.guide import study_guide_agent
                output, usage = await stream_agent_output(study_guide_agent, prompt)
                log_tokens_generated(usage)
                
                if mode == "note" and target:
                    await _insert_with_approval(target, "study guide", output, topic_content)
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")

        asyncio.run(run_stream())


@make.command()
def note(
    topic: str = typer.Argument(..., help="Topic to create a note about"),
    sources: Optional[List[str]] = typer.Option(None, "--source", "-s", help="Sources to base the note on"),
    focus: Optional[str] = typer.Option(None, "--focus", "-f", help="Specific aspect to focus on"),
    with_flashcards: bool = typer.Option(False, "--with-flashcards", help="Include flashcards in the note"),
    with_exercises: bool = typer.Option(False, "--with-exercises", help="Include exercises in the note"),
    where: Optional[str] = typer.Option(None, "--where", "-w", help="Output: 'here' (print), note name/path, or auto-create (default)")
):
    """Generate a structured learning note from sources.
    
    When --with-flashcards or --with-exercises is specified, uses a pipeline:
    1. Create base note (with approval)
    2. Add flashcards using flashcard_agent (with approval)
    3. Add exercises using exercise_agent (with approval)
    
    Examples:
        obx make note "Momentum" -s "textbook.pdf"
        obx make note "Topic" --with-flashcards --with-exercises
        obx make note "Topic" --where "Custom Note Name"
        obx make note "Topic" --where here  # Print to stdout
    """
    with command_timer():
        ensure_configured()
        log_model_usage("Model", settings.primary_model)
        
        # Determine where to write the note (handles None, "here", or note name)
        mode, target = _determine_note_path(topic, where)
        # For new notes, don't include topic as note content (it doesn't exist yet)
        _, sources_content, pdf_paths = _gather_sources(topic, sources, include_topic_note=False)
    
        # Build prompt for NOTE ONLY (no flashcards/exercises - they come later in pipeline)
        prompt = f"Create a structured learning note about: {topic}\n\n"
        if sources_content:
            prompt += f"--- Source Materials ---\n{sources_content}\n---\n\n"
        prompt += (
            "Use search_vault to find related context from existing notes.\n"
            "DO NOT include flashcards or exercises - just create the note content.\n"
        )
        if focus:
            prompt += f"Focus on: {focus}\n"
        
        console.print(f"[bold blue]Generating Note for '{topic}'...[/bold blue]")
    
        async def run_stream():
            nonlocal target
            try:
                from obx.agents.flashcard_agent import note_agent
                output, usage = await stream_agent_output(note_agent, prompt)
                log_tokens_generated(usage)
                
                if mode == "here":
                    # Output was already streamed to console
                    if with_flashcards or with_exercises:
                        console.print("\n[yellow]Note: Cannot add flashcards/exercises when printing to stdout.[/yellow]")
                    return
                
                # Mode is "note" - write to file
                if not target:
                    console.print("[red]Error:[/red] No target path determined.")
                    return
                
                # Check if note already exists
                is_new_note = not target.exists()
                
                # If it's a new note and user didn't specify a folder, check for agent suggestion
                final_target = target
                if is_new_note and not where:
                    yaml_data = get_note_yaml(output)
                    suggested_folder = yaml_data.get("folder")
                    if suggested_folder:
                        # Clean suggested folder (handle lists or bracketed strings)
                        if isinstance(suggested_folder, list):
                            folder_str = suggested_folder[0] if suggested_folder else "."
                        else:
                            folder_str = str(suggested_folder).strip("[] ")
                        
                        if folder_str and folder_str != ".":
                            vault = settings.vault_path
                            out_dir = (vault / folder_str).resolve()
                            # Safety check: ensure within vault
                            if str(out_dir).startswith(str(vault.resolve())):
                                final_target = out_dir / target.name
                                if final_target != target:
                                    console.print(f"[dim]Agent suggested folder: {folder_str}[/dim]")
                
                # Allow user to override target path for new notes
                if is_new_note:
                    final_path_str = await questionary.text(
                        "Destination path (relative to vault root):",
                        default=str(final_target.relative_to(settings.vault_path)),
                    ).ask_async()
                    if final_path_str:
                        final_target = (settings.vault_path / final_path_str).resolve()
                        # Ensure suffix
                        if not final_target.suffix:
                            final_target = final_target.with_suffix(".md")
                        # Ensure dir exists
                        final_target.parent.mkdir(parents=True, exist_ok=True)
                
                target = final_target
                is_new_note = not target.exists()
                note_created = False
                
                if is_new_note:
                    # NEW NOTE: Write directly to file with diff preview
                    console.print(f"\n[bold cyan]── Creating New Note: {target.name} ──[/bold cyan]")
                    
                    # Show diff against empty file
                    Editor.generate_diff("", output, target.name)
                    
                    console.print()
                    if await questionary.confirm("Create this note?", default=True).ask_async():
                        # Initialize scores (will be 0.0 for new notes)
                        flashcards, exercises = get_all_learning_items(output)
                        final_content = update_note_scores(target, {
                            'flashcards': flashcards,
                            'exercises': exercises
                        }, output)
                        target.write_text(final_content, encoding="utf-8")
                        console.print(f"[green]✓ Created note: {target}[/green]")
                        note_created = True
                    else:
                        console.print("[yellow]Note creation cancelled.[/yellow]")
                        return
                else:
                    # EXISTING NOTE: Append using same logic as flashcard/exercise commands
                    console.print(f"\n[bold cyan]── Appending to Existing Note: {target.name} ──[/bold cyan]")
                    
                    original_content = target.read_text(encoding="utf-8")
                    
                    # Append the generated content at the end with diff
                    if await _append_at_end_with_diff(
                        target,
                        "note content",
                        output,
                        original_content,
                        section_header=""  # No section header for full note content
                    ):
                        note_created = True
                
                if not note_created:
                    return
                
                # STEP 2: Add flashcards if requested
                if with_flashcards and target and target.exists():
                    console.print(f"\n[bold blue]Generating Flashcards for '{topic}'...[/bold blue]")
                    
                    # Run flashcard command as a subprocess for complete isolation
                    # This avoids event loop / MCP resource conflicts
                    cmd = [sys.executable, "-m", "obx.cli.main", "make", "flashcard", topic, "--where", str(target)]
                    if sources:
                        for s in sources:
                            cmd.extend(["--source", s])
                            
                    process = await asyncio.create_subprocess_exec(*cmd)
                    await process.wait()
                
                # STEP 3: Add exercises if requested
                if with_exercises and target and target.exists():
                    console.print(f"\n[bold blue]Generating Exercises for '{topic}'...[/bold blue]")
                    
                    # Run exercise command as a subprocess for complete isolation
                    cmd = [sys.executable, "-m", "obx.cli.main", "make", "exercise", topic, "--where", str(target)]
                    if sources:
                        for s in sources:
                            cmd.extend(["--source", s])
                            
                    process = await asyncio.create_subprocess_exec(*cmd)
                    await process.wait()
                    
            except Exception as e:
                # Extract underlying exception from TaskGroup if present
                error_msg = str(e)
                if hasattr(e, '__cause__') and e.__cause__:
                    error_msg = f"{error_msg}\nCaused by: {e.__cause__}"
                if hasattr(e, 'exceptions'):
                    # ExceptionGroup or TaskGroup
                    console.print(f"[red]Error:[/red] {error_msg}")
                    for idx, exc in enumerate(e.exceptions, 1):
                        console.print(f"  [red]Sub-exception {idx}:[/red] {exc}")
                        if hasattr(exc, '__traceback__'):
                            import traceback
                            console.print(f"[dim]{''.join(traceback.format_tb(exc.__traceback__))}[/dim]")
                else:
                    console.print(f"[red]Error:[/red] {error_msg}")
                    import traceback
                    console.print(f"[dim]{traceback.format_exc()}[/dim]")


        asyncio.run(run_stream())


@make.command()
def flashcard(
    topic: str = typer.Argument(..., help="Note name or topic to create flashcards for"),
    sources: Optional[List[str]] = typer.Option(None, "--source", "-s", help="Additional sources (PDFs, URLs, notes)"),
    count: int = typer.Option(10, "--count", "-c", help="Approximate number of flashcards"),
    where: str = typer.Option("here", "--where", "-w", help="Output: 'here' (print) or note name/path to insert into")
):
    """Generate flashcards for a topic or note.
    
    The topic/note is the PRIMARY source. Use --source for additional materials.
    When inserting into a note, flashcards are added under a ## Flashcards header.
    You will review and approve with diff visualization.
    
    Examples:
        obx make flashcard "Groups"
        obx make flashcard "Groups" -s "/path/to/textbook.pdf" --where "Groups"
        obx make flashcard "Linear Algebra" -c 15 --where "Linear Algebra Notes"
    """
    with command_timer():
        ensure_configured()
        log_model_usage("Model", settings.primary_model)
        
        mode, target = _resolve_where(where)
        topic_content, sources_content, pdf_paths = _gather_sources(topic, sources)

    
        prompt = f"Generate approximately {count} flashcards for: {topic}\n\n"
        if sources_content:
            prompt += f"--- Source Materials ---\n{sources_content}\n---\n\n"
        prompt += (
            "Focus on key concepts, definitions, and important facts that are worth memorizing.\n"
            "Use the proper flashcard format with initial state metadata.\n"
            "IMPORTANT: The #flashcard tag must ALWAYS come AFTER the question on the SAME LINE.\n"
            "Format: Question : Answer #flashcard {\"state\":\"learning\",...}\n"
            "Use search_vault if you need additional context from related notes.\n"
        )
        
        console.print(f"[bold blue]Generating Flashcards for '{topic}'...[/bold blue]")
    
        async def run_stream():
            try:
                from obx.agents.flashcard_agent import flashcard_agent
                output, usage = await stream_agent_output(flashcard_agent, prompt)
                log_tokens_generated(usage)
                
                if mode == "note" and target:
                    # Use simple append at end with diff approval
                    await _append_at_end_with_diff(
                        target, "flashcards", output, topic_content, "## Flashcards"
                    )
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")

        asyncio.run(run_stream())


@make.command()
def exercise(
    topic: str = typer.Argument(..., help="Note name or topic to create exercises for"),
    sources: Optional[List[str]] = typer.Option(None, "--source", "-s", help="Additional sources (PDFs, URLs, notes)"),
    count: int = typer.Option(5, "--count", "-c", help="Approximate number of exercises"),
    where: str = typer.Option("here", "--where", "-w", help="Output: 'here' (print) or note name/path to insert into")
):
    """Generate or extract exercises for a topic or note.
    
    The topic/note is the PRIMARY source. Use --source for additional materials.
    When inserting into a note, exercises are added under a ## Exercises header.
    You will review and approve with diff visualization.
    
    Examples:
        obx make exercise "Calculus"
        obx make exercise "Groups" -s "/path/to/textbook.pdf" --where "Groups"
    """
    with command_timer():
        ensure_configured()
        log_model_usage("Model", settings.primary_model)
        
        mode, target = _resolve_where(where)
        topic_content, sources_content, pdf_paths = _gather_sources(topic, sources)

    
        prompt = f"Generate or extract approximately {count} exercises for: {topic}\n\n"
        if sources_content:
            prompt += f"--- Source Materials ---\n{sources_content}\n---\n\n"
        prompt += (
            "IMPORTANT: If the source contains existing exercises (like textbook problems), "
            "prioritize extracting and formatting those. Only generate new exercises if needed.\n"
            "Order exercises by difficulty and dependency. Use the proper exercise format.\n"
            "Use search_vault if you need additional context from related notes.\n"
        )
        
        console.print(f"[bold blue]Generating Exercises for '{topic}'...[/bold blue]")
    
        async def run_stream():
            try:
                from obx.agents.exercise_agent import exercise_agent
                output, usage = await stream_agent_output(exercise_agent, prompt)
                log_tokens_generated(usage)
                
                if mode == "note" and target:
                    # Use simple append at end with diff approval
                    await _append_at_end_with_diff(
                        target, "exercises", output, topic_content, "## Exercises"
                    )
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")

        asyncio.run(run_stream())
