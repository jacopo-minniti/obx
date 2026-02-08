import typer
import asyncio
from obx.utils.ui import console, stream_agent_output, command_timer, log_model_usage, log_tokens_generated
from obx.cli.utils import ensure_configured
from obx.agents.chat import obx_agent
from obx.core.config import settings

def chat_command():
    """Start an interactive chat session with the AI agent."""
    ensure_configured()
    console.print("[bold green]obx chat initialized.[/bold green] Type 'exit' to quit.")
    
    while True:
        user_input = typer.prompt("You")
        if user_input.lower() in ["exit", "quit"]:
            break
        
        with command_timer():
            log_model_usage("Model", settings.reasoning_model)
            try:
                _, usage = asyncio.run(stream_agent_output(obx_agent, user_input))
                log_tokens_generated(usage)
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
