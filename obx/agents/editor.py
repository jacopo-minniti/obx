from pydantic_ai import Agent
from pydantic import BaseModel, Field
from obx.core.config import settings
from obx.utils.models import resolve_model

# --- Editor Agent ("obx insert") ---

class EditProposal(BaseModel):
    reasoning: str = Field(description="Why this insertion point was chosen.")
    target_context: str = Field(description="A unique text snippet (~1-3 lines) from the original file to serve as an anchor. MUST exist exactly in the file.")
    insertion_mode: str = Field(description="Where to insert relative to anchor: 'before' or 'after'.", pattern="^(before|after)$")
    content_to_insert: str = Field(description="The formatted content to insert.")

editor_agent = Agent(
    model=resolve_model(settings.primary_model), # Use smart model for robust anchor finding
    system_prompt=(
        "You are an expert editor. Your task is to insert new content into an existing Markdown note seamlessly. "
        "1. Read the provided Note Content. "
        "2. Determine the BEST semantic location for the user's new content. "
        "3. Identify a UNIQUE text anchor (context) in the note to attach the new content to. "
        "   - The anchor must be EXACTLY present in the text. "
        "   - Prefer headers or distinct paragraph endings. "
        "   - Return 'after' mode usually, unless 'before' a specific header is better. "
        "4. Return the proposal as a strictly formatted JSON object matching this schema: "
        "{'reasoning': str, 'target_context': str, 'insertion_mode': 'before'|'after', 'content_to_insert': str}. "
        "Do NOT output markdown code blocks, just the RAW JSON string."
    ),
    deps_type=None
)
