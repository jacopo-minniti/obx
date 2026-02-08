import typer
import asyncio
from typing import List

from obx.utils.ui import console, stream_agent_output, command_timer, log_model_usage, log_tokens_generated
from obx.cli.utils import ensure_configured
from obx.agents.guide import study_guide_agent
from obx.core.config import settings

make = typer.Typer(help="Tools for creating content (guides, flashcards, etc).")

@make.command()
def guide(
    sources: List[str] = typer.Option(..., "--source", "-s", help="Path to PDF, Vault Note name, or URL"),
    focus: str = typer.Option(None, "--focus", "-f", help="Specific topic to focus the guide on."),
    where: str = typer.Option("vault", "--where", help="Output destination: here or vault.")
):
    """Generate a study guide from sources."""
    with command_timer():
        ensure_configured()
        log_model_usage("Model", settings.primary_model)
    
        # Simple prompt construction
        prompt = (
            f"Create a study guide based on the following sources: {sources}\n"
            "If exercises are explicitly present in the sources, reference them by number/name and source, "
            "prioritize them, and explain the order. If no exercises exist, create targeted exercises.\n"
        )
        if focus:
            prompt += f"Focus strictly on: {focus}\n"
        
        console.print("[bold blue]Generating Study Guide...[/bold blue]")
    
        async def run_stream():
            try:
                output, usage = await stream_agent_output(study_guide_agent, prompt)
                log_tokens_generated(usage)
                if where == "vault":
                    if not settings.output_dir:
                        console.print("[red]Error:[/red] Output directory not configured. Run [bold]obx config[/bold].")
                        return
                    if output:
                        from obx.utils.fs import write_generated_note
                        result = write_generated_note(output)
                        if result.startswith("Error"):
                            console.print(f"[red]{result}[/red]")
                        else:
                            console.print(f"[green]{result}[/green]")
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")

        asyncio.run(run_stream())
