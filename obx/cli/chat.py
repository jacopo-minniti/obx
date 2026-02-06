import typer
from rich.markdown import Markdown
from obx.utils.ui import console, format_markdown
from obx.cli.utils import ensure_configured
from obx.agents.chat import obx_agent

def chat_command():
    """Start an interactive chat session with the AI agent."""
    ensure_configured()
    console.print("[bold green]obx chat initialized.[/bold green] Type 'exit' to quit.")
    
    while True:
        user_input = typer.prompt("You")
        if user_input.lower() in ["exit", "quit"]:
            break
        
        with console.status("Thinking..."):
            try:
                result = obx_agent.run_sync(user_input)
                console.print(f"[bold blue]obx:[/bold blue] {result.output}")
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")

def ask_command(question: str):
    """Ask a question about your notes."""
    ensure_configured()
    with console.status("Searching..."):
        result = obx_agent.run_sync(f"Answer this question based on my notes: {question}")
        console.print(Markdown(format_markdown(result.output)))
