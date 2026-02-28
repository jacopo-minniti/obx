import typer
import asyncio
import questionary
from typing import Optional
from obx.utils.ui import console, stream_agent_output, command_timer, log_model_usage, log_tokens_generated
from obx.cli.utils import ensure_configured
from obx.core.config import settings

def chat_command(initial_msg: Optional[str] = None):
    """Start an interactive chat session with the AI agent."""
    from obx.agents.chat import obx_agent
    
    ensure_configured()
    
    if initial_msg:
        with command_timer():
            log_model_usage("Model", settings.reasoning_model)
            try:
                asyncio.run(stream_agent_output(obx_agent, initial_msg))
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
    else:
        console.print("[bold green]obx chat initialized.[/bold green] Type 'exit' to quit.")
    
    while True:
        try:
            user_input = questionary.text("You:", qmark="❯").ask()
            if not user_input or user_input.lower() in ["exit", "quit", "q"]:
                break
            
            with command_timer():
                log_model_usage("Model", settings.reasoning_model)
                try:
                    _, usage = asyncio.run(stream_agent_output(obx_agent, user_input))
                    log_tokens_generated(usage)
                except Exception as e:
                    console.print(f"[red]Error:[/red] {e}")
        except KeyboardInterrupt:
            break
    console.print("[dim]Chat session closed.[/dim]")
