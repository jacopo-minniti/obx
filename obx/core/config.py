from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

HOME_DIR = Path.home()
OBX_DIR = HOME_DIR / ".obx"
ENV_FILE = OBX_DIR / ".env"

class Settings(BaseSettings):
    vault_path: Optional[Path] = Field(None, description="Path to the Obsidian Vault")
    # Models
    primary_model: str = Field("gemini-3-flash-preview", description="Fast/Small model for routine tasks")
    reasoning_model: str = Field("gemini-3-pro-preview", description="Smart/Reasoner model for complex tasks")
    ocr_model: str = Field("gemini-flash-lite-latest", description="Model for OCR tasks")

    # Reasoning Effort (OpenRouter specific)
    openrouter_reasoning_effort: Optional[str] = Field(None, description="Reasoning effort for OpenRouter models (high, medium, low, etc.)")

    # API Keys - Pydantic settings will automatically read from env vars like OPENAI_API_KEY if not set here
    # We keep them Optional to allow falling back to system env vars
    gemini_api_key: Optional[str] = Field(None, description="Google Gemini API Key")
    openai_api_key: Optional[str] = Field(None, description="OpenAI API Key")
    anthropic_api_key: Optional[str] = Field(None, description="Anthropic API Key")
    openrouter_api_key: Optional[str] = Field(None, description="OpenRouter API Key")
    cohere_api_key: Optional[str] = Field(None, description="Cohere API Key")
    voyage_api_key: Optional[str] = Field(None, description="Voyage AI API Key")
    
    # Embedding Settings
    embedding_provider: str = Field("sentence-transformers", description="Embedding provider")
    embedding_model: str = Field("all-MiniLM-L6-v2", description="Embedding model name")

    # Persona
    mood: str = Field("helpful", description="Persona/Mood of the assistant")

    # Default output directory for generated notes (relative to vault)
    output_dir: Optional[str] = Field(None, description="Default output folder for generated notes (relative to vault)")
    
    # Exclusions
    exclude_folders: List[str] = Field(default_factory=list, description="List of folder paths (relative to vault) to exclude")

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding='utf-8',
        extra='ignore'
    )

    @property
    def is_configured(self) -> bool:
        return self.vault_path is not None and self.vault_path.exists()

    def save(self):
        """Persist current settings to ~/.obx/.env"""
        OBX_DIR.mkdir(parents=True, exist_ok=True)
        import json
        with open(ENV_FILE, "w") as f:
            if self.vault_path:
                f.write(f"VAULT_PATH={self.vault_path}\n")
            
            # API Keys - Only write if they were explicitly set in the config session
            # If they are None, we don't write them, allowing system env vars to take likely precedence or just remaining unset
            if self.gemini_api_key: f.write(f"GEMINI_API_KEY={self.gemini_api_key}\n")
            if self.openai_api_key: f.write(f"OPENAI_API_KEY={self.openai_api_key}\n")
            if self.anthropic_api_key: f.write(f"ANTHROPIC_API_KEY={self.anthropic_api_key}\n")
            if self.openrouter_api_key: f.write(f"OPENROUTER_API_KEY={self.openrouter_api_key}\n")
            if self.cohere_api_key: f.write(f"COHERE_API_KEY={self.cohere_api_key}\n")
            if self.voyage_api_key: f.write(f"VOYAGE_API_KEY={self.voyage_api_key}\n")
            
            # Models
            f.write(f"PRIMARY_MODEL={self.primary_model}\n")
            f.write(f"REASONING_MODEL={self.reasoning_model}\n")
            f.write(f"OCR_MODEL={self.ocr_model}\n")
            
            if self.openrouter_reasoning_effort:
                f.write(f"OPENROUTER_REASONING_EFFORT={self.openrouter_reasoning_effort}\n")
            
            f.write(f"MOOD={self.mood}\n")
            
            # Embeddings
            f.write(f"EMBEDDING_PROVIDER={self.embedding_provider}\n")
            f.write(f"EMBEDDING_MODEL={self.embedding_model}\n")

            if self.output_dir:
                f.write(f"OUTPUT_DIR={self.output_dir}\n")
            
            if self.exclude_folders:
                f.write(f"EXCLUDE_FOLDERS={json.dumps(self.exclude_folders)}\n")

settings = Settings()
