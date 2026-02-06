import typer
import asyncio
from typing import List
from rich.live import Live
from rich.markdown import Markdown

from obx.utils.ui import console, format_markdown
from obx.cli.utils import ensure_configured
from obx.agents.guide import study_guide_agent

make = typer.Typer(help="Tools for creating content (guides, flashcards, etc).")

@make.command()
def guide(
    sources: List[str] = typer.Option(..., "--source", "-s", help="Path to PDF, Vault Note name, or URL"),
    focus: str = typer.Option(None, "--focus", "-f", help="Specific topic to focus the guide on.")
):
    """Generate a study guide from sources."""
    ensure_configured()
    
    # Simple prompt construction
    prompt = f"Create a study guide based on the following sources: {sources}\n"
    if focus:
        prompt += f"Focus strictly on: {focus}\n"
        
    console.print("[bold blue]Generating Study Guide...[/bold blue]")
    
    async def run_stream():
        try:
            async with study_guide_agent.run_stream(prompt) as result:
                with Live(Markdown(""), refresh_per_second=12, console=console) as live:
                    async for snapshot in result.stream():
                        live.update(Markdown(format_markdown(snapshot)))
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")

    asyncio.run(run_stream())
