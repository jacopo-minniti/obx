import typer
from typing import Optional
# Import config app early since it's used for the help menu and registration
from obx.cli.config import config_app

app = typer.Typer(help="obx: AI-native CLI for Obsidian.md")

# Register commands
app.add_typer(config_app, name="config")

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    message: Optional[str] = typer.Argument(None, help="Initial prompt to talk to the orchestrator.")
):
    """obx: AI-native CLI for Obsidian.md"""
    if ctx.invoked_subcommand is None:
        from obx.cli.chat import chat_command
        return chat_command(initial_msg=message)

@app.command(name="index")
def index(
    clear: bool = typer.Option(False, "--clear", help="Clear the existing index and re-index everything.")
):
    """Index the vault for search."""
    from obx.cli.search import index_command
    return index_command(clear=clear)

@app.command(name="search")
def search(
    topic: str,
    where: str = typer.Option("here", "--where", "-w", help="Output: 'here' (print) or note name/path to append to")
):
    """Hybrid search for notes relevant to a topic."""
    from obx.cli.search import search_command
    return search_command(topic=topic, where=where)

@app.command(name="ask")
def ask(
    question: str,
    where: str = typer.Option("here", "--where", "-w", help="Output: 'here' (print) or note name/path to append to"),
    mode: str = typer.Option(None, "--mode", help="Force 'topic' mode to research the question instead of answering about a specific note.")
):
    """Ask a question and get answers based on vault content."""
    from obx.cli.search import ask_command
    return ask_command(question=question, where=where, mode=mode)

@app.command(name="chat")
def chat(
    message: str = typer.Argument(None, help="Initial message to start the chat with.")
):
    """Chat with the primary orchestrator (the main agent)."""
    from obx.cli.chat import chat_command
    return chat_command(initial_msg=message)

@app.command(name="open")
def open_note(note: str = typer.Argument(None, help="Note name to open")):
    """Open a note in Obsidian."""
    from obx.cli.io import open_command
    return open_command(note=note)

@app.command(name="read")
def read_note(note: str = typer.Argument(None, help="Note name to read")):
    """Read a note from Obsidian."""
    from obx.cli.io import read_command
    return read_command(note=note)

@app.command(name="insert")
def insert_note(
    topic: str = typer.Argument(..., help="What to write about"),
    where: str = typer.Option(None, "--where", "-w", help="Where to insert (note name)")
):
    """Write/append information to a note."""
    from obx.cli.io import insert_command
    return insert_command(topic=topic, where=where)

@app.command(name="recall")
def recall():
    """Start a recall exercise."""
    from obx.cli.recall import recall_command
    return recall_command()

# Sub-typers (also lazy-loaded when triggered)
def make_callback(ctx: typer.Context):
    # This ensures that when 'obx make' is called, we load the full 'make' app
    from obx.cli.make import make as make_app
    # Typer doesn't easily allow late registration this way for sub-typers 
    # but we can just use a wrapper function if needed.
    # However, add_typer can be used with a string? No.
    pass

# For sub-typers we can just add them and accept the import cost ONLY if we call 'make'
# Wait, add_typer(make_app) imports 'make_app'.
# To truly lazy-load sub-typers, we'd need to manually handle the dispatch or use a wrapper.
# But for now, let's just use the lazy command pattern for top-level ones.
from obx.cli.make import make as make_app
app.add_typer(make_app, name="make")

if __name__ == "__main__":
    app()
