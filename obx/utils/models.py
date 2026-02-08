from __future__ import annotations

from typing import Any
from obx.core.config import settings
from obx.utils.ui import normalize_model_id

def resolve_model(model_id: str) -> Any:
    """
    Resolve a model identifier into a Pydantic-AI model instance when needed.
    Falls back to returning the model_id string for non-special cases.
    """
    normalized = normalize_model_id(model_id)
    if not normalized:
        return model_id

    if normalized.startswith("openrouter:"):
        # Expected format: openrouter:provider/model
        _, name = normalized.split(":", 1)
        try:
            from pydantic_ai.models.openrouter import OpenRouterModel
            from pydantic_ai.providers.openrouter import OpenRouterProvider
        except Exception as e:
            raise RuntimeError(
                "OpenRouter support requires pydantic-ai-slim[openrouter]. "
                "Install it with: uv add \"pydantic-ai-slim[openrouter]\""
            ) from e

        api_key = settings.openrouter_api_key
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Run `obx config keys` and set the OpenRouter API Key."
            )
        provider = OpenRouterProvider(
            api_key=api_key,
            app_title="obx",
        )
        return OpenRouterModel(name, provider=provider)

    return normalized
