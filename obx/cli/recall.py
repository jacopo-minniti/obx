"""CLI command for recall sessions with flashcards and exercises."""

import typer
import asyncio
import questionary
import json
from datetime import datetime
from questionary import Style
from typing import Optional
from pathlib import Path

from obx.utils.ui import (
    console,
    stream_agent_output,
    command_timer,
    log_model_usage,
    log_tokens_generated,
    render_markdown,
    extract_usage,
)
from obx.cli.utils import ensure_configured, update_note_scores
from obx.core.config import settings
from obx.utils.fs import (
    resolve_note_path,
    get_learning_scores,
    update_learning_scores,
    update_note_yaml,
)
from obx.core.learning_parser import (
    get_all_learning_items,
    update_flashcard_in_content,
    update_exercise_in_content,
)
from obx.core.flashcard import Flashcard, FlashcardAlgorithm, Rating, calculate_memory_score
from obx.core.exercise import Exercise, ExerciseGrade, calculate_exercise_score
from obx.core.recall import RecallOrchestrator, TopicTypeEstimator
from obx.agents.recall_agent import recall_agent, exercise_reviewer_agent
from obx.rag.engine import RAG


# Custom style for questionary
RECALL_STYLE = Style([
    ('qmark', 'fg:#36cdc4 bold'),
    ('question', 'bold'),
    ('pointer', 'fg:#36cdc4 bold'),
    ('highlighted', 'fg:#36cdc4 bold'),
    ('answer', 'fg:white bold'),  # Use white for answers, not cyan
])


def recall_command(
    name: str = typer.Argument(..., help="Note name or topic to recall"),
    flashcards_only: bool = typer.Option(False, "--flashcards-only", "-f", help="Only review flashcards"),
    exercises_only: bool = typer.Option(False, "--exercises-only", "-e", help="Only review exercises"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum items per session"),
):
    """Start an interactive recall session."""
    async def run():
        await _run_recall_session(name, flashcards_only, exercises_only, limit)
    
    asyncio.run(run())


async def _run_recall_session(
    name: str,
    flashcards_only: bool,
    exercises_only: bool,
    limit: int,
):
    with command_timer():
        ensure_configured()
        log_model_usage("Model", settings.reasoning_model)
        
        console.print(f"[bold blue]Starting Recall Session:[/bold blue] {name}")
        
        # Resolve target: note or topic
        target_path = resolve_note_path(name)
        is_topic_mode = target_path is None
        
        if is_topic_mode:
            console.print(f"[dim]No exact note match for '{name}'. Treating as topic...[/dim]")
            note_paths = _find_topic_notes(name)
            if not note_paths:
                console.print("[red]No relevant notes found for this topic.[/red]")
                return
            console.print(f"[green]Found {len(note_paths)} relevant notes.[/green]")
        else:
            console.print(f"[green]Found note:[/green] {target_path.name}")
            note_paths = [target_path]
        
        # Gather flashcards and exercises from all notes
        all_flashcards = []
        all_exercises = []
        note_content_map = {}  # path -> content for updates
        note_items_map = {}  # path -> (flashcards, exercises) for score tracking
        
        for path in note_paths:
            try:
                content = path.read_text(encoding="utf-8")
                note_content_map[path] = content
                flashcards, exercises = get_all_learning_items(content)
                
                # Track which items belong to which note
                note_items = {
                    'flashcards': flashcards,
                    'exercises': exercises,
                }
                note_items_map[path] = note_items
                all_flashcards.extend(flashcards)
                all_exercises.extend(exercises)
                
                # Recalculate and update YAML scores for this note immediately
                # This ensures scores are up-to-date (handles decayed memory or deleted items)
                new_content = update_note_scores(path, note_items, content)
                if new_content != content:
                    note_content_map[path] = new_content
                    path.write_text(new_content, encoding="utf-8")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not read/update {path}: {e}[/yellow]")
        
        if not all_flashcards and not all_exercises:
            console.print("[yellow]No flashcards or exercises found in the note(s).[/yellow]")
            console.print("[dim]Use 'obx make flashcard' or 'obx make exercise' to add some.[/dim]")
            return
        
        # Display stats
        console.print(f"\n[bold]Session Overview:[/bold]")
        console.print(f"  Flashcards: {len(all_flashcards)}")
        console.print(f"  Exercises: {len(all_exercises)}")
        
        # Get topic preference
        topic = name if is_topic_mode else ""
        fc_weight, ex_weight = TopicTypeEstimator.get_preference_weights(topic)
        if ex_weight > fc_weight:
            console.print(f"  [dim]Topic favors: exercises ({ex_weight:.0%})[/dim]")
        elif fc_weight > ex_weight:
            console.print(f"  [dim]Topic favors: flashcards ({fc_weight:.0%})[/dim]")
        
        console.print()
        
        # Interactive session
        items_reviewed = 0
        early_review_mode = False
        
        while items_reviewed < limit:
            # Select next item
            if not early_review_mode:
                # Normal mode: get due items
                next_item = RecallOrchestrator.select_next(
                    all_flashcards,
                    all_exercises,
                    topic=topic,
                    flashcards_only=flashcards_only,
                    exercises_only=exercises_only,
                )
                
                if next_item is None:
                    # All due items done - ask about early review
                    console.print("\n[green]✓ All due items reviewed![/green]")
                    console.print("[dim]You can continue with early review to reinforce your memory.[/dim]")
                    console.print("[dim]Note: Early reviews use scaled intervals (won't disrupt your schedule).[/dim]")
                    
                    if await questionary.confirm(
                        "Continue with early review?",
                        default=False,
                        style=RECALL_STYLE,
                    ).ask_async():
                        early_review_mode = True
                        console.print("\n[cyan]Entering early review mode...[/cyan]")
                        continue
                    else:
                        break
            else:
                # Early review mode: get non-due items ranked by proximity
                next_item = RecallOrchestrator.select_next_early(
                    all_flashcards,
                    all_exercises,
                    topic=topic,
                    flashcards_only=flashcards_only,
                    exercises_only=exercises_only,
                )
                
                if next_item is None:
                    console.print("[green]No more cards available for early review![/green]")
                    break
                
                # Show early review indicator
                if isinstance(next_item, Flashcard) and next_item.due_date:
                    now = datetime.now()
                    time_until_due = next_item.due_date - now
                    if time_until_due.total_seconds() > 0:
                        if time_until_due.days > 0:
                            console.print(f"[dim]⏰ Early review (due in {time_until_due.days}d)[/dim]")
                        else:
                            hours = int(time_until_due.total_seconds() / 3600)
                            console.print(f"[dim]⏰ Early review (due in {hours}h)[/dim]")
            
            if isinstance(next_item, Flashcard):
                updated = await _review_flashcard(next_item)
                # Update in global list
                all_flashcards = [c if c.id != updated.id else updated for c in all_flashcards]
                
                # Find which note contains this flashcard and update it
                for path, content in note_content_map.items():
                    try:
                        # Update flashcard content
                        new_content = update_flashcard_in_content(content, updated)
                        note_content_map[path] = new_content
                        
                        # Update the flashcard in the note's item tracking
                        note_items = note_items_map[path]
                        note_items['flashcards'] = [
                            c if c.id != updated.id else updated 
                            for c in note_items['flashcards']
                        ]
                        
                        # Recalculate and update YAML scores for this note
                        new_content = update_note_scores(path, note_items, new_content)
                        note_content_map[path] = new_content
                        
                        # Write updated content to file
                        path.write_text(new_content, encoding="utf-8")
                        break  # Found the note with this card
                    except ValueError:
                        continue  # Card not in this note
            else:
                updated = await _review_exercise(next_item)
                # Update in global list
                all_exercises = [e if e.id != updated.id else updated for e in all_exercises]
                
                # Find which note contains this exercise and update it
                for path, content in note_content_map.items():
                    try:
                        # Update exercise content
                        new_content = update_exercise_in_content(content, updated)
                        note_content_map[path] = new_content
                        
                        # Update the exercise in the note's item tracking
                        note_items = note_items_map[path]
                        note_items['exercises'] = [
                            e if e.id != updated.id else updated 
                            for e in note_items['exercises']
                        ]
                        
                        # Recalculate and update YAML scores for this note
                        new_content = update_note_scores(path, note_items, new_content)
                        note_content_map[path] = new_content
                        
                        # Write updated content to file
                        path.write_text(new_content, encoding="utf-8")
                        break  # Found the note with this exercise
                    except ValueError:
                        continue  # Exercise not in this note
            
            items_reviewed += 1
        
        # Calculate overall session scores for display
        memory_score = calculate_memory_score(all_flashcards)
        exercise_score = calculate_exercise_score(all_exercises)
        
        console.print(f"\n[bold]Session Complete![/bold]")
        console.print(f"  Items reviewed: {items_reviewed}")
        console.print(f"  Memory score: {memory_score:.0%}")
        console.print(f"  Exercise score: {exercise_score:.0%}")



def _find_topic_notes(topic: str) -> list[Path]:
    """Find notes related to a topic using search."""
    try:
        rag = RAG()
        if not rag.index_exists():
            console.print("[yellow]Search index not found. Run 'obx index' first.[/yellow]")
            return []
        
        results = rag.search(topic, limit=5)
        paths = []
        seen = set()
        
        for r in results:
            source = r.get("source", "")
            if source and source not in seen:
                path = resolve_note_path(source.replace(".md", ""))
                if path:
                    paths.append(path)
                    seen.add(source)
        
        return paths
    except Exception:
        return []


async def _review_flashcard(card: Flashcard) -> Flashcard:
    """Interactive flashcard review."""
    console.print("\n" + "─" * 50)
    console.print("[bold cyan]📚 Flashcard[/bold cyan]")
    console.print()
    
    # Show question
    render_markdown(f"**Q:** {card.question}")
    console.print()
    
    # Wait for user to reveal
    await questionary.press_any_key_to_continue(
        "Press any key to reveal answer...",
        style=RECALL_STYLE,
    ).ask_async()
    
    # Show answer
    console.print()
    render_markdown(f"**A:** {card.answer}")
    console.print()
    
    # Get rating with keyboard shortcuts
    console.print("[bold]How did you do?[/bold]")
    console.print("  [dim]1[/dim] Again   [dim]2[/dim] Hard   [dim]3[/dim] Good   [dim]4[/dim] Easy")
    console.print("  [dim](Use arrow keys and Enter, or press 1-4)[/dim]")
    
    rating_choices = [
        questionary.Choice("1. Again (forgot completely)", value=Rating.AGAIN, shortcut_key="1"),
        questionary.Choice("2. Hard (struggled to recall)", value=Rating.HARD, shortcut_key="2"),
        questionary.Choice("3. Good (recalled with effort)", value=Rating.GOOD, shortcut_key="3"),
        questionary.Choice("4. Easy (recalled instantly)", value=Rating.EASY, shortcut_key="4"),
    ]
    
    rating = await questionary.select(
        "",
        choices=rating_choices,
        style=RECALL_STYLE,
        pointer="❯",
        use_shortcuts=True,
    ).ask_async()
    
    if rating is None:
        rating = Rating.GOOD  # Default if cancelled
    updated = FlashcardAlgorithm.apply_rating(card, rating)
    
    # Show next review time
    if updated.due_date:
        now = datetime.now()
        delta = updated.due_date - now
        if delta.total_seconds() < 3600:
            time_str = f"{int(delta.total_seconds() / 60)} minutes"
        elif delta.total_seconds() < 86400:
            time_str = f"{int(delta.total_seconds() / 3600)} hours"
        else:
            time_str = f"{int(delta.total_seconds() / 86400)} days"
        console.print(f"[dim]Next review in: {time_str}[/dim]")
    
    return updated


async def _review_exercise(ex: Exercise) -> Exercise:
    """Interactive exercise review with AI dialogue loop."""
    console.print("\n" + "─" * 50)
    console.print(f"[bold cyan]📝 Exercise[/bold cyan] [dim](Difficulty: {ex.difficulty})[/dim]")
    console.print()
    
    # Show exercise
    render_markdown(ex.prompt)
    console.print()
    
    while True:
        # Get user's attempt
        console.print("[bold]Your response:[/bold] [dim](type 'hint' for help, or 'skip' to give up)[/dim]")
        
        user_response = await questionary.text(
            "",
            multiline=True,
            style=RECALL_STYLE,
        ).ask_async()
        
        if not user_response or user_response.strip().lower() == "skip":
            console.print("[yellow]Exercise skipped.[/yellow]")
            ex.record_attempt(ExerciseGrade.INCORRECT)
            return ex
            
        if user_response.strip().lower() == "hint":
            # Explicit request for hint
            user_msg = "Please give me a hint."
        else:
            user_msg = user_response
            
        # Add to history
        ex.add_chat_message("user", user_msg)
        
        # Build prompt for agent
        full_context = (
            f"Exercise: {ex.prompt}\n\n"
            f"Static Hints available: {', '.join(ex.hints) if ex.hints else 'None'}\n\n"
        )
        
        # Use history in prompt
        history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in ex.chat_history])
        eval_prompt = f"{full_context}\nFeedback History:\n{history_str}\n\nReview the latest student message and provide guidance."

        console.print("\n[dim]Tutor is thinking...[/dim]")
        
        try:
            # We parse JSON manually for cross-version compatibility
            result = await exercise_reviewer_agent.run(eval_prompt)
            output = result.output.strip()
            
            # Extract JSON from potential code blocks
            if "```json" in output:
                output = output.split("```json")[1].split("```")[0].strip()
            elif "```" in output:
                output = output.split("```")[1].split("```")[0].strip()
            
            review = json.loads(output)
            feedback = review.get("feedback", "")
            grade = review.get("grade", 0)
            status = review.get("status", "CONTINUE")
            
            log_tokens_generated(extract_usage(getattr(result, "usage", None)))
            
            # Show feedback
            console.print("\n[bold]Tutor:[/bold]")
            render_markdown(feedback)
            console.print()
            
            # Update exercise state
            ex.add_chat_message("assistant", feedback)
            ex.grade = ExerciseGrade(grade)
            
            if status == "CORRECT":
                console.print("[bold green]✓ Correct![/bold green]")
                ex.attempts += 1 # Manual increment as we are in a loop
                ex.last_attempt = datetime.now()
                return ex
            
        except Exception as e:
            console.print(f"[red]Review error: {e}[/red]")
            # Fall back to self-grading if loop breaks
            grade = await _self_grade_exercise()
            ex.record_attempt(grade)
            return ex


async def _self_grade_exercise() -> ExerciseGrade:
    """Let user self-grade if AI fails."""
    answer = await questionary.select(
        "How would you rate your response?",
        choices=[
            "Not attempted (0)",
            "Incorrect (1)",
            "Partial (2)",
            "Correct (3)",
        ],
        style=RECALL_STYLE,
    ).ask_async()
    
    grade_map = {
        "Not attempted (0)": ExerciseGrade.NOT_ATTEMPTED,
        "Incorrect (1)": ExerciseGrade.INCORRECT,
        "Partial (2)": ExerciseGrade.PARTIAL,
        "Correct (3)": ExerciseGrade.CORRECT,
    }
    
    return grade_map.get(answer, ExerciseGrade.NOT_ATTEMPTED)

