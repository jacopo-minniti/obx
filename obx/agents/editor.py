from pydantic_ai import Agent
from pydantic import BaseModel, Field
from typing import List
from obx.core.config import settings
from obx.utils.models import resolve_model

# --- Editor Agent ("obx insert") ---

class EditProposal(BaseModel):
    reasoning: str = Field(description="Why this insertion point was chosen.")
    target_context: str = Field(description="A unique text snippet (~1-3 lines) from the original file to serve as an anchor. MUST exist exactly in the file.")
    insertion_mode: str = Field(description="Where to insert relative to anchor: 'before' or 'after'.", pattern="^(before|after)$")
    content_to_insert: str = Field(description="The formatted content to insert.")


class InsertProposals(BaseModel):
    """Multiple insertion proposals for organic content placement."""
    proposals: List[EditProposal] = Field(description="List of insertion proposals, ordered by position in document.")


editor_agent = Agent(
    model=resolve_model(settings.primary_model),
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


# --- Learning Content Insert Agent ---
# This agent places flashcards/exercises ORGANICALLY throughout a note

insert_learning_agent = Agent(
    model=resolve_model(settings.primary_model),
    system_prompt="""\
You are an expert learning content editor. Your task is to insert flashcards or exercises INTO an existing note at CONTEXTUALLY APPROPRIATE locations.

## Goal
Insert the provided learning content (flashcards/exercises) at semantically meaningful positions throughout the note - NOT just at the end!

## Placement Strategy
1. Place flashcards/exercises AFTER the paragraph or section that covers the relevant concept
2. Group 1-3 related flashcards together after their relevant section
3. A final bulk section at the end is OK for general/summary flashcards
4. Each insertion should be self-contained and make sense in its location

## CRITICAL: Flashcard Format
Use this EXACT format consistently:

**One-line flashcard (simple Q&A):**
```
Question text : Answer text #flashcard {"state":"learning","step":0,"interval":null,"ease":2.5,"due":null}
```

**Multi-line flashcard (complex content):**
```
Question text : #flashcard {"state":"learning","step":0,"interval":null,"ease":2.5,"due":null}
---
Multi-line answer here
Can include code, lists, etc.
---
```

The `#flashcard` tag ALWAYS comes after the question on the SAME LINE.

## Output Format
Return a JSON object with an array of insertion proposals:
```json
{
  "proposals": [
    {
      "reasoning": "Why this location makes sense",
      "target_context": "Exact unique text anchor from the note (1-3 lines)",
      "insertion_mode": "after",
      "content_to_insert": "The flashcard(s) to insert here"
    },
    ...
  ]
}
```

## Rules
1. Each anchor MUST exist EXACTLY in the original note
2. Prefer headers or paragraph endings as anchors
3. Process the note top-to-bottom
4. Return ONLY raw JSON, no markdown code blocks
""",
    deps_type=None
)

