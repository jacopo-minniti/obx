import typer
from obx.utils.ui import console

# Import commands
from obx.cli.config import config_command
from obx.cli.search import index_command, search_command, explain_command
from obx.cli.chat import chat_command, ask_command
from obx.cli.io import open_command, read_command, insert_command
from obx.cli.make import make as make_app

app = typer.Typer(help="obx: AI-native CLI for Obsidian.md")

# Register commands
app.command(name="config")(config_command)
app.command(name="index")(index_command)
app.command(name="search")(search_command)
app.command(name="explain")(explain_command)
app.command(name="chat")(chat_command)
app.command(name="ask")(ask_command)
app.command(name="open")(open_command)
app.command(name="read")(read_command)
app.command(name="insert")(insert_command)

# Register sub-typers
app.add_typer(make_app, name="make")

if __name__ == "__main__":
    app()
