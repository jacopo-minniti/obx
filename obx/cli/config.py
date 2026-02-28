import typer
import questionary
from questionary import Choice
from pathlib import Path
import os
from obx.core.config import settings
from obx.utils.ui import console, command_timer

config_app = typer.Typer(help="Configure obx settings.")

MODEL_PROVIDERS = ["Google Gemini", "OpenAI", "Anthropic", "OpenRouter", "Other..."]
EMBEDDING_PROVIDERS = ["sentence-transformers (local)", "openai", "google", "cohere", "voyageai"]

def _prompt_keep_current(label: str, current: str, secret: bool = False) -> str:
    if current:
        console.print(f"[dim]Current {label}: {current}[/dim]")
    val = typer.prompt(label, default="", hide_input=secret, show_default=False)
    return val.strip() if val.strip() else current

def _select_provider(title: str, default: str) -> str:
    return questionary.select(
        title,
        choices=MODEL_PROVIDERS,
        default=default
    ).ask()

def _select_embedding_provider(default: str) -> str:
    return questionary.select(
        "Select Embedding Provider:",
        choices=EMBEDDING_PROVIDERS,
        default=default
    ).ask()

def _configure_vault() -> Path | None:
    current_vault = settings.vault_path or ""
    vault_path_str = _prompt_keep_current("Obsidian Vault Path", str(current_vault))
    try:
        vault_path = Path(vault_path_str).expanduser().resolve()
        if not vault_path.exists():
            console.print(f"[yellow]Warning: Path {vault_path} does not exist.[/yellow]")
        settings.vault_path = vault_path
        return vault_path
    except Exception as e:
        console.print(f"[red]Invalid path: {e}[/red]")
        return None

def _configure_output_dir():
    console.print("\n[bold]Generated Notes Location[/bold]")
    output_default = settings.output_dir or ""
    output_dir = _prompt_keep_current("Default output folder (relative to vault, blank to disable)", output_default)
    settings.output_dir = output_dir if output_dir else None

def _configure_exclusions(vault_path: Path):
    console.print("\n[bold]Excluded Folders[/bold]")
    console.print("[dim]Select folders to exclude from indexing (space to toggle).[/dim]")
    
    folder_choices = []
    max_depth = 2
    for root, dirs, files in os.walk(vault_path):
        dirs.sort()
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        rel_path = Path(root).relative_to(vault_path)
        depth = len(rel_path.parts)
        if str(rel_path) == ".":
            depth = 0
        
        if depth > max_depth:
            del dirs[:]
            continue
            
        if depth == 0:
            continue

        indent = "  " * (depth - 1)
        folder_name = rel_path.name
        display_name = f"{indent}📂 {folder_name}"
        
        is_checked = False
        if str(rel_path) in settings.exclude_folders:
            is_checked = True
        else:
            for excluded in settings.exclude_folders:
                try:
                    if rel_path.is_relative_to(excluded):
                        is_checked = True
                        break
                except ValueError:
                    continue
        
        folder_choices.append(Choice(
            title=display_name,
            value=str(rel_path),
            checked=is_checked
        ))
        
    if folder_choices:
        excluded_choices = questionary.checkbox(
            "Exclude Folders:",
            choices=folder_choices,
            style=questionary.Style([
                ('qmark', 'fg:#36cdc4 bold'),
                ('question', 'bold'),
                ('pointer', 'fg:#36cdc4 bold'),
                ('highlighted', 'fg:#36cdc4 bold'),
                ('selected', 'fg:#36cdc4'),
            ]),
            instruction="(Space to select. Selecting a folder automatically excludes all its subfolders.)"
        ).ask()
        
        if excluded_choices is not None:
            settings.exclude_folders = excluded_choices
    else:
        console.print("[dim]No folders found to exclude.[/dim]")

def _default_model_for(provider: str, kind: str) -> str:
    if provider == "Google Gemini":
        return "gemini-3-flash-preview" if kind == "primary" else "gemini-3-pro-preview" if kind == "reasoning" else "gemini-flash-lite-latest"
    if provider == "OpenAI":
        return "gpt-5-mini-2025-08-07" if kind == "primary" else "gpt-5.2-2025-12-11" if kind == "reasoning" else "gpt-4o"
    if provider == "Anthropic":
        return "claude-3-haiku" if kind == "primary" else "claude-3-5-sonnet" if kind == "reasoning" else "claude-3-haiku-20240307"
    if provider == "OpenRouter":
        return "openrouter:anthropic/claude-sonnet-4-5"
    return ""

def _configure_model(kind: str):
    console.print(f"\n[bold]{kind.title()} Model[/bold]")
    provider = _select_provider(f"{kind.title()} Agent Provider:", "Google Gemini")
    default_model = _default_model_for(provider, kind)
    current = getattr(settings, f"{kind}_model")
    model_id = _prompt_keep_current(f"{kind.title()} Model ID", current or default_model)
    setattr(settings, f"{kind}_model", model_id)

    if provider == "OpenRouter":
        console.print("\n[bold]OpenRouter Reasoning Effort[/bold]")
        console.print("[dim]Control reasoning tokens for thinking models (e.g. o1, deepseek-r1).[/dim]")
        
        choices = ["(none)", "high", "medium", "low", "minimal"]
        # Map None to "(none)" for display
        current_effort = settings.openrouter_reasoning_effort or "(none)"
        
        selected = questionary.select(
            "Reasoning Effort:",
            choices=choices,
            default=current_effort
        ).ask()
        
        if selected == "(none)":
            settings.openrouter_reasoning_effort = None
        else:
            settings.openrouter_reasoning_effort = selected

def _configure_keys():
    console.print("\n[bold]API Keys[/bold]")
    console.print("[dim]Leave empty to keep unset or use global environment variables (recommended). Values are masked.[/dim]")
    key_map = [
        ("Google Gemini", "gemini_api_key"),
        ("OpenAI", "openai_api_key"),
        ("Anthropic", "anthropic_api_key"),
        ("OpenRouter", "openrouter_api_key"),
        ("Cohere", "cohere_api_key"),
        ("Voyage AI", "voyage_api_key"),
    ]
    for label, attr_name in key_map:
        current_val = getattr(settings, attr_name)
        if current_val:
            console.print(f"[dim]Current {label} API Key: (set)[/dim]")
        new_val = typer.prompt(f"{label} API Key", default="", hide_input=True, show_default=False)
        if new_val.strip():
            setattr(settings, attr_name, new_val.strip())

def _configure_embedding():
    console.print("\n[bold]Embedding Configuration[/bold]")
    default_prov = "sentence-transformers (local)"
    if settings.embedding_provider in [p.split()[0] for p in EMBEDDING_PROVIDERS]:
        for p in EMBEDDING_PROVIDERS:
            if p.startswith(settings.embedding_provider):
                default_prov = p
                break
                
    provider_choice = _select_embedding_provider(default_prov)
    if not provider_choice:
        provider_choice = "sentence-transformers (local)"
    
    provider = provider_choice.split(" ")[0]
    settings.embedding_provider = provider
    
    default_models = {
        "sentence-transformers": "all-MiniLM-L6-v2",
        "openai": "text-embedding-3-small",
        "google": "text-embedding-004",
        "cohere": "embed-english-v3.0",
        "voyageai": "voyage-large-2"
    }
    
    current_model_default = default_models.get(provider, "")
    settings.embedding_model = _prompt_keep_current("Embedding Model Name", settings.embedding_model or current_model_default)

def _save_and_print():
    settings.save()
    console.print(f"\n[green]✔ Configuration saved to {settings.model_config['env_file']}[/green]")
    console.print(f"Primary Agent: [bold]{settings.primary_model}[/bold]")
    console.print(f"Reasoning Agent: [bold]{settings.reasoning_model}[/bold]")
    console.print(f"OCR Agent: [bold]{settings.ocr_model}[/bold]")
    if settings.openrouter_reasoning_effort:
        console.print(f"OpenRouter Reasoning: [bold]{settings.openrouter_reasoning_effort}[/bold]")
    if settings.exclude_folders:
        console.print(f"Excluded: {len(settings.exclude_folders)} folders")

@config_app.callback(invoke_without_command=True)
def config_command(ctx: typer.Context):
    """Run the full configuration wizard."""
    if ctx.invoked_subcommand:
        return
    with command_timer():
        console.print("[bold cyan]obx Configuration[/bold cyan]")
        vault_path = _configure_vault()
        if not vault_path:
            return
        _configure_output_dir()
        if vault_path.exists():
            _configure_exclusions(vault_path)
        console.print("\n[bold]Model Selection[/bold]")
        _configure_model("primary")
        _configure_model("reasoning")
        _configure_model("ocr")
        _configure_keys()
        _configure_embedding()
        _save_and_print()

@config_app.command("model")
def config_model(
    kind: str = typer.Argument(..., help="Which model to configure: primary, reasoning, or ocr.")
):
    """Configure a single model."""
    with command_timer():
        kind = kind.lower().strip()
        if kind not in {"primary", "reasoning", "ocr"}:
            console.print("[red]Error:[/red] Model type must be one of: primary, reasoning, ocr.")
            raise typer.Exit(code=1)
        _configure_model(kind)
        _save_and_print()

@config_app.command("embedding")
def config_embedding():
    """Configure embedding provider and model."""
    with command_timer():
        _configure_embedding()
        _save_and_print()

@config_app.command("keys")
def config_keys():
    """Configure API keys."""
    with command_timer():
        _configure_keys()
        _save_and_print()

@config_app.command("vault")
def config_vault():
    """Configure vault path."""
    with command_timer():
        _configure_vault()
        _save_and_print()

@config_app.command("output")
def config_output():
    """Configure default output folder for generated notes."""
    with command_timer():
        _configure_output_dir()
        _save_and_print()

@config_app.command("exclude")
def config_exclude():
    """Configure excluded folders."""
    with command_timer():
        vault = settings.vault_path
        if not vault:
            console.print("[red]Error:[/red] Vault path not configured.")
            raise typer.Exit(code=1)
        _configure_exclusions(vault)
        _save_and_print()
