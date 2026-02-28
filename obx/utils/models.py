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
            from openai import AsyncOpenAI
        except Exception as e:
            raise RuntimeError(
                "OpenRouter support requires pydantic-ai-slim[openrouter] and openai. "
                "Install it with: uv add \"pydantic-ai-slim[openrouter]\""
            ) from e

        api_key = settings.openrouter_api_key
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Run `obx config keys` and set the OpenRouter API Key."
            )

        # Create client specifically to inject reasoning parameters if needed
        client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        
        # Inject reasoning effort if configured
        if settings.openrouter_reasoning_effort:
            original_create = client.chat.completions.create
            
            async def create_with_reasoning(*args, **kwargs):
                if "extra_body" not in kwargs:
                    kwargs["extra_body"] = {}
                
                # Add reasoning config if not present
                # usage: obx config model -> OpenRouter -> Reasoning Effort
                reasoning = kwargs["extra_body"].get("reasoning")
                if not reasoning:
                    kwargs["extra_body"]["reasoning"] = {
                        "effort": settings.openrouter_reasoning_effort
                    }
                
                return await original_create(*args, **kwargs)
            
            # Monkey patch the create method on this specific client instance
            client.chat.completions.create = create_with_reasoning

        provider = OpenRouterProvider(
            openai_client=client,
            app_title="obx",
        )
        return OpenRouterModel(name, provider=provider)

    return normalized
