import typer
from obx.core.config import settings
from obx.utils.ui import console

def ensure_configured():
    if not settings.is_configured:
        console.print("[red]Error: obx is not configured.[/red]")
        console.print("Run [bold]obx config[/bold] to set up your vault path and API keys.")
        raise typer.Exit(code=1)
