"""Parse and serialize flashcards and exercises in markdown files."""

import re
import json
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass

from obx.core.flashcard import Flashcard, FlashcardState
from obx.core.exercise import Exercise, ExerciseGrade


# Regex patterns for parsing

# One-line flashcard: Question : Answer #flashcard {...}
ONELINE_FLASHCARD_PATTERN = re.compile(
    r'^(?P<question>.+?)\s*:\s*(?P<answer>.+?)\s*#flashcard\s*(?P<state>\{.*?\})?\s*$',
    re.MULTILINE
)

# Multi-line flashcard: #flashcard {...} followed by Q, ---, A, ---
MULTILINE_FLASHCARD_START = re.compile(
    r'^#flashcard\s*(?P<state>\{.*?\})?\s*(?P<tags>(?:#\w+\s*)*)$',
    re.MULTILINE
)

# Exercise: #exercise {...} followed by prompt, ---
EXERCISE_PATTERN = re.compile(
    r'^#exercise\s*(?P<state>\{.*?\})?\s*(?P<tags>(?:#\w+\s*)*)$',
    re.MULTILINE
)

# Alternative micro-card format with emoji
MICRO_FLASHCARD_PATTERN = re.compile(
    r'^(?P<question>.+?)\s*:\s*(?P<answer>.+?)\s*(?:⚡️|🧠)\s*(?P<state>\{.*?\})?\s*$',
    re.MULTILINE
)


@dataclass
class ParsedItem:
    """A parsed learning item with its position in the content."""
    item: Any  # Flashcard or Exercise
    start_pos: int
    end_pos: int
    original_text: str


def _parse_state_json(state_str: Optional[str]) -> Dict[str, Any]:
    """Parse state JSON string, returning empty dict on failure."""
    if not state_str:
        return {}
    try:
        return json.loads(state_str.strip())
    except json.JSONDecodeError:
        return {}


def _extract_block_content(content: str, start_pos: int) -> Tuple[str, int]:
    """
    Extract content from start_pos until the next --- delimiter or end.
    Returns (content, end_position).
    """
    remaining = content[start_pos:]
    
    # Find the next ---
    hr_match = re.search(r'\n---\s*\n?', remaining)
    if hr_match:
        block = remaining[:hr_match.start()]
        end = start_pos + hr_match.end()
    else:
        block = remaining
        end = len(content)
    
    return block.strip(), end


def parse_flashcards(content: str) -> List[ParsedItem]:
    """
    Parse all flashcards from markdown content.
    
    Supports:
    - One-line format: Question : Answer #flashcard {...}
    - Micro format: Question : Answer ⚡️ {...}
    - Multi-line format: #flashcard {...}
      Question
      ---
      Answer
      ---
    """
    results = []
    
    # Parse one-line flashcards
    for match in ONELINE_FLASHCARD_PATTERN.finditer(content):
        question = match.group('question').strip()
        answer = match.group('answer').strip()
        state_dict = _parse_state_json(match.group('state'))
        
        card = Flashcard.from_state_dict(question, answer, state_dict)
        results.append(ParsedItem(
            item=card,
            start_pos=match.start(),
            end_pos=match.end(),
            original_text=match.group(0)
        ))
    
    # Parse micro flashcards
    for match in MICRO_FLASHCARD_PATTERN.finditer(content):
        # Skip if already parsed as one-line (overlapping patterns)
        if any(p.start_pos <= match.start() < p.end_pos for p in results):
            continue
        
        question = match.group('question').strip()
        answer = match.group('answer').strip()
        state_dict = _parse_state_json(match.group('state'))
        
        card = Flashcard.from_state_dict(question, answer, state_dict)
        results.append(ParsedItem(
            item=card,
            start_pos=match.start(),
            end_pos=match.end(),
            original_text=match.group(0)
        ))
    
    # Parse multi-line flashcards
    for match in MULTILINE_FLASHCARD_START.finditer(content):
        start = match.start()
        state_dict = _parse_state_json(match.group('state'))
        
        # Extract tags
        tags_str = match.group('tags') or ""
        tags = [t.strip().lstrip('#') for t in tags_str.split() if t.strip().startswith('#')]
        
        # Get the question (until first ---)
        question_start = match.end()
        question_text, after_q = _extract_block_content(content, question_start)
        
        if not question_text:
            continue
        
        # Get the answer (until next ---)
        answer_text, end_pos = _extract_block_content(content, after_q)
        
        if not answer_text:
            answer_text = ""  # Allow empty answers for #spaced style
        
        card = Flashcard.from_state_dict(question_text, answer_text, state_dict, tags)
        results.append(ParsedItem(
            item=card,
            start_pos=start,
            end_pos=end_pos,
            original_text=content[start:end_pos]
        ))
    
    return results


def parse_exercises(content: str) -> List[ParsedItem]:
    """
    Parse all exercises from markdown content.
    
    Format:
    #exercise {...}
    Exercise prompt text
    
    ---
    """
    results = []
    
    for match in EXERCISE_PATTERN.finditer(content):
        start = match.start()
        state_dict = _parse_state_json(match.group('state'))
        
        # Extract tags
        tags_str = match.group('tags') or ""
        tags = [t.strip().lstrip('#') for t in tags_str.split() if t.strip().startswith('#')]
        
        # Get the prompt (until ---)
        prompt_start = match.end()
        prompt_text, end_pos = _extract_block_content(content, prompt_start)
        
        if not prompt_text:
            continue
        
        # Parse hints if present (lines starting with "Hint:")
        lines = prompt_text.split('\n')
        prompt_lines = []
        hints = []
        chat_history = []
        
        in_history = False
        current_role = None
        current_content = []
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('###### Feedback History'):
                in_history = True
                continue
            
            if in_history:
                if stripped.startswith('**User**:'):
                    if current_role:
                        chat_history.append({"role": current_role, "content": '\n'.join(current_content).strip()})
                    current_role = "user"
                    current_content = [stripped[9:].strip()]
                elif stripped.startswith('**Assistant**:'):
                    if current_role:
                        chat_history.append({"role": current_role, "content": '\n'.join(current_content).strip()})
                    current_role = "assistant"
                    current_content = [stripped[14:].strip()]
                elif stripped.startswith('**Agent**:'):
                    if current_role:
                        chat_history.append({"role": current_role, "content": '\n'.join(current_content).strip()})
                    current_role = "assistant"
                    current_content = [stripped[10:].strip()]
                elif current_role:
                    current_content.append(line)
                continue

            if stripped.lower().startswith('hint:'):
                hints.append(stripped[5:].strip())
            else:
                prompt_lines.append(line)
        
        if current_role:
            chat_history.append({"role": current_role, "content": '\n'.join(current_content).strip()})
            
        prompt = '\n'.join(prompt_lines).strip()
        
        exercise = Exercise.from_state_dict(prompt, state_dict, hints, tags, chat_history=chat_history)
        results.append(ParsedItem(
            item=exercise,
            start_pos=start,
            end_pos=end_pos,
            original_text=content[start:end_pos]
        ))
    
    return results


def serialize_flashcard(card: Flashcard, multiline: bool = False) -> str:
    """
    Serialize a flashcard to markdown format.
    
    Args:
        card: The flashcard to serialize
        multiline: If True, use multi-line format; otherwise one-line
    """
    state_json = json.dumps(card.to_state_dict(), separators=(',', ':'))
    
    if multiline or '\n' in card.question or '\n' in card.answer:
        # Multi-line format
        tags_str = ' '.join(f'#{t}' for t in card.tags) if card.tags else ''
        return f"""#flashcard {state_json} {tags_str}
{card.question}

---
{card.answer}

---"""
    else:
        # One-line format
        return f"{card.question} : {card.answer} #flashcard {state_json}"


def serialize_exercise(ex: Exercise) -> str:
    """Serialize an exercise to markdown format."""
    state_json = json.dumps(ex.to_state_dict(), separators=(',', ':'))
    tags_str = ' '.join(f'#{t}' for t in ex.tags) if ex.tags else ''
    
    result = f"#exercise {state_json} {tags_str}\n{ex.prompt}"
    
    if ex.hints:
        result += "\n" + "\n".join(f"Hint: {h}" for h in ex.hints)
    
    if ex.chat_history:
        result += "\n\n###### Feedback History"
        for msg in ex.chat_history:
            role_name = "User" if msg["role"] == "user" else "Assistant"
            result += f"\n**{role_name}**: {msg['content']}"
    
    result += "\n\n---"
    return result


def update_flashcard_in_content(content: str, card: Flashcard) -> str:
    """
    Update a flashcard's state in the markdown content.
    
    Matches by card ID or question text.
    """
    parsed = parse_flashcards(content)
    
    for p in parsed:
        if p.item.id == card.id or p.item.question.strip() == card.question.strip():
            # Found the card - replace with updated version
            is_multiline = '\n---' in p.original_text
            new_text = serialize_flashcard(card, multiline=is_multiline)
            return content[:p.start_pos] + new_text + content[p.end_pos:]
    
    # Card not found - this shouldn't happen in normal use
    raise ValueError(f"Flashcard not found in content: {card.id}")


def update_exercise_in_content(content: str, ex: Exercise) -> str:
    """
    Update an exercise's state in the markdown content.
    
    Matches by exercise ID.
    """
    parsed = parse_exercises(content)
    
    for p in parsed:
        if p.item.id == ex.id:
            new_text = serialize_exercise(ex)
            return content[:p.start_pos] + new_text + content[p.end_pos:]
    
    # Exercise not found
    raise ValueError(f"Exercise not found in content: {ex.id}")


def get_all_learning_items(content: str) -> Tuple[List[Flashcard], List[Exercise]]:
    """Parse all flashcards and exercises from content."""
    flashcards = [p.item for p in parse_flashcards(content)]
    exercises = [p.item for p in parse_exercises(content)]
    return flashcards, exercises


def add_flashcards_to_content(content: str, cards: List[Flashcard], section: str = "Flashcards") -> str:
    """
    Add flashcards to content, creating a section if needed.
    
    Appends to existing section or creates new one at the end.
    """
    section_header = f"## {section}"
    
    # Check if section exists
    if section_header in content:
        # Find section end (next ## or end of content)
        section_start = content.index(section_header)
        section_content_start = section_start + len(section_header)
        
        remaining = content[section_content_start:]
        next_section = re.search(r'\n## ', remaining)
        
        if next_section:
            insert_pos = section_content_start + next_section.start()
        else:
            insert_pos = len(content)
        
        # Add cards before next section
        cards_text = "\n\n" + "\n\n".join(serialize_flashcard(c) for c in cards)
        return content[:insert_pos] + cards_text + content[insert_pos:]
    else:
        # Add new section at the end
        cards_text = f"\n\n{section_header}\n\n" + "\n\n".join(serialize_flashcard(c) for c in cards)
        return content + cards_text


def add_exercises_to_content(content: str, exercises: List[Exercise], section: str = "Exercises") -> str:
    """
    Add exercises to content, creating a section if needed.
    
    Appends to existing section or creates new one at the end.
    """
    section_header = f"## {section}"
    
    if section_header in content:
        section_start = content.index(section_header)
        section_content_start = section_start + len(section_header)
        
        remaining = content[section_content_start:]
        next_section = re.search(r'\n## ', remaining)
        
        if next_section:
            insert_pos = section_content_start + next_section.start()
        else:
            insert_pos = len(content)
        
        exercises_text = "\n\n" + "\n\n".join(serialize_exercise(e) for e in exercises)
        return content[:insert_pos] + exercises_text + content[insert_pos:]
    else:
        exercises_text = f"\n\n{section_header}\n\n" + "\n\n".join(serialize_exercise(e) for e in exercises)
        return content + exercises_text
