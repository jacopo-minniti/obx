import typer
import questionary
from questionary import Choice
from pathlib import Path
import os
from obx.core.config import settings
from obx.utils.ui import console

def config_command():
    """Configure obx settings (Vault path, Models, API keys)."""
    console.print("[bold cyan]obx Configuration[/bold cyan]")
    
    # 1. Vault Path
    current_vault = settings.vault_path or ""
    # Use user input or keep current
    vault_path_str = typer.prompt("Obsidian Vault Path", default=str(current_vault))
    try:
        vault_path = Path(vault_path_str).expanduser().resolve()
        if not vault_path.exists():
             console.print(f"[yellow]Warning: Path {vault_path} does not exist.[/yellow]")
             # We allow it, but warn
    except Exception as e:
        console.print(f"[red]Invalid path: {e}[/red]")
        return
    settings.vault_path = vault_path

    # 2. Folder Exclusion (Tree-ish view)
    if vault_path.exists():
        console.print("\n[bold]Excluded Folders[/bold]")
        console.print("[dim]Select folders to exclude from indexing (space to toggle).[/dim]")
        
        folder_choices = []
        
        # Walk the directory tree (limit depth to avoid massive lists)
        max_depth = 2 # 0 is root, 1 is top-level folders, 2 is subfolders
        
        # We need a stable sort
        for root, dirs, files in os.walk(vault_path):
            # Sort dirs in-place to ensure alphabetical walk
            dirs.sort()
            
            # Filter hidden dirs (inplace mod for os.walk)
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            rel_path = Path(root).relative_to(vault_path)
            depth = len(rel_path.parts)
            
            if str(rel_path) == ".":
                depth = 0
            
            if depth > max_depth:
                # modifying dirs in place stops os.walk from going deeper
                del dirs[:]
                continue
                
            # Don't add root itself as a choice, only its children
            if depth == 0:
                continue

            # Create choice
            # Indent based on depth (depth 1 = 0 indent, depth 2 = 2 spaces etc)
            indent = "  " * (depth - 1)
            folder_name = rel_path.name
            display_name = f"{indent}📂 {folder_name}"
            
            # Check if this folder path (string) is in settings, or if any of its parents are
            # This ensures that if we previously excluded 'A', 'A/B' shows as checked.
            is_checked = False
            
            # 1. Exact match
            if str(rel_path) in settings.exclude_folders:
                is_checked = True
            else:
                # 2. Parent match
                # Check if this path is technically a child of any already excluded path
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
                    ('selected', 'fg:#36cdc4'), # Checkbox selection color
                ]),
                instruction="(Space to select. Selecting a folder automatically excludes all its subfolders.)"
            ).ask()
            
            if excluded_choices is not None:
                settings.exclude_folders = excluded_choices
        else:
             console.print("[dim]No folders found to exclude.[/dim]")

    # 3. Models Selection
    console.print("\n[bold]Model Selection[/bold]")
    
    model_providers = ["Google Gemini", "OpenAI", "Anthropic", "Other..."]
    
    # --- Primary Model ---
    p_provider = questionary.select(
        "Primary Agent Provider:",
        choices=model_providers,
        default="Google Gemini"
    ).ask()

    p_default = settings.primary_model 
    # Use specific new defaults if they match the selected provider type
    if p_provider == "Google Gemini":
        p_default = "gemini-3-flash-preview"
    elif p_provider == "OpenAI":
        p_default = "gpt-5-mini-2025-08-07"
    elif p_provider == "Anthropic":
        # Best guess for a 'fast' model if valid
        if "claude" not in p_default: p_default = "claude-3-haiku"
    
    settings.primary_model = typer.prompt("Primary Model ID", default=p_default)

    # --- Reasoning Model ---
    r_provider = questionary.select(
        "Reasoning Agent Provider:",
        choices=model_providers,
        default="Google Gemini"
    ).ask()

    r_default = settings.reasoning_model
    if r_provider == "Google Gemini":
        r_default = "gemini-3-pro-preview"
    elif r_provider == "OpenAI":
        r_default = "gpt-5.2-2025-12-11"
    elif r_provider == "Anthropic":
        if "claude" not in r_default: r_default = "claude-3-5-sonnet"

    settings.reasoning_model = typer.prompt("Reasoning Model ID", default=r_default)

    # --- OCR Model ---
    o_provider = questionary.select(
        "OCR Agent Provider:",
        choices=model_providers,
        default="Google Gemini"
    ).ask()

    o_default = settings.ocr_model
    if o_provider == "Google Gemini":
        o_default = "gemini-flash-lite-latest"
    elif o_provider == "OpenAI":
        o_default = "gpt-4o"
    elif o_provider == "Anthropic":
        if "claude" not in o_default: o_default = "claude-3-haiku-20240307"

    settings.ocr_model = typer.prompt("OCR Model ID", default=o_default)

    # 4. API Keys
    console.print("\n[bold]API Keys[/bold]")
    console.print("[dim]Leave empty to keep unset or use global environment variables (recommended). Values are masked.[/dim]")
    
    key_map = [
        ("Google Gemini", "gemini_api_key"),
        ("OpenAI", "openai_api_key"),
        ("Anthropic", "anthropic_api_key"),
        ("Cohere", "cohere_api_key"),
        ("Voyage AI", "voyage_api_key"),
    ]
    
    for label, attr_name in key_map:
        current_val = getattr(settings, attr_name)
        prompt_text = f"{label} API Key"
        if current_val:
            prompt_text += f" [dim](currently set)[/dim]"
            
        new_val = typer.prompt(prompt_text, default="", hide_input=True, show_default=False)
        
        if new_val.strip():
            setattr(settings, attr_name, new_val.strip())

    # 5. Embedding Configuration
    console.print("\n[bold]Embedding Configuration[/bold]")
    providers = ["sentence-transformers (local)", "openai", "google", "cohere", "voyageai"]
    
    # Check if current provider is valid choice
    default_prov = "sentence-transformers (local)"
    if settings.embedding_provider in [p.split()[0] for p in providers]:
        # find the matching choice string
        for p in providers:
            if p.startswith(settings.embedding_provider):
                default_prov = p
                break
                
    provider_choice = questionary.select(
        "Select Embedding Provider:",
        choices=providers,
        default=default_prov
    ).ask()
    
    if not provider_choice:
        provider_choice = "sentence-transformers (local)"
    
    provider = provider_choice.split(" ")[0]
    settings.embedding_provider = provider
    
    # Models default
    default_models = {
        "sentence-transformers": "all-MiniLM-L6-v2",
        "openai": "text-embedding-3-small",
        "google": "text-embedding-004",
        "cohere": "embed-english-v3.0",
        "voyageai": "voyage-large-2"
    }
    
    current_model_default = default_models.get(provider, "")
    
    model_name = typer.prompt("Embedding Model Name", default=settings.embedding_model if settings.embedding_provider == provider else current_model_default)
    settings.embedding_model = model_name

    # Save
    settings.save()
    console.print(f"\n[green]✔ Configuration saved to {settings.model_config['env_file']}[/green]")
    console.print(f"Primary Agent: [bold]{settings.primary_model}[/bold]")
    console.print(f"Reasoning Agent: [bold]{settings.reasoning_model}[/bold]")
    console.print(f"OCR Agent: [bold]{settings.ocr_model}[/bold]")
    
    if settings.exclude_folders:
        console.print(f"Excluded: {len(settings.exclude_folders)} folders")
