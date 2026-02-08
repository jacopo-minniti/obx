from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.theme import Theme
from rich.text import Text
import re
import urllib.parse
import json
from typing import Any, Optional, Dict
from contextlib import contextmanager
import time
from obx.core.config import settings

# Custom theme for better markdown aesthetics vs readability
obx_theme = Theme({
    "markdown": "white",
    "markdown.text": "white",
    "markdown.paragraph": "white",
    "markdown.em": "white italic",           # Emphasized text (italic)
    "markdown.strong": "bold white",         # Strong text (bold)
    "markdown.s": "white strike",            # Strikethrough
    "markdown.h1": "bold cyan underline",
    "markdown.h2": "bold bright_blue",
    "markdown.h3": "bold blue",
    "markdown.h4": "bold white",
    "markdown.h5": "white",
    "markdown.h6": "white",
    "markdown.link": "bright_blue underline",
    "markdown.link_url": "bright_blue underline",
    "markdown.code_block": "white on #1e1e1e",
    "markdown.code": "bold yellow", 
    "markdown.item": "white",                # Bullets
    "markdown.item.bullet": "white",         # Bullet points
    "markdown.item.number": "white",         # Numbered lists
    "markdown.list": "white",                # List content
    "markdown.block_quote": "dim white",
    "markdown.hr": "white",                  # Horizontal rule
})

console = Console(theme=obx_theme, style="white")

@contextmanager
def command_timer():
    """Measure and print elapsed time for a command."""
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        console.print(f"Elapsed: {elapsed:.2f}s")

def log_model_usage(label: str, model: str) -> None:
    console.print(f"{label}: {model}")

def log_embedding_usage(provider: str, model: str) -> None:
    console.print(f"Embedding: {provider} {model}")

def _extract_usage(usage_obj: Any) -> Dict[str, int]:
    if usage_obj is None:
        return {}
    if isinstance(usage_obj, dict):
        return {k: int(v) for k, v in usage_obj.items() if isinstance(v, (int, float))}
    usage = {}
    for key in (
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "response_tokens",
    ):
        val = getattr(usage_obj, key, None)
        if isinstance(val, (int, float)):
            usage[key] = int(val)
    return usage

def _tokens_generated(usage: Dict[str, int]) -> Optional[int]:
    for key in ("output_tokens", "completion_tokens", "response_tokens"):
        if key in usage:
            return usage[key]
    return usage.get("total_tokens")

def log_tokens_generated(usage: Dict[str, int]) -> None:
    tokens = _tokens_generated(usage)
    if tokens is not None:
        console.print(f"Tokens: {tokens}")

def extract_usage(usage_obj: Any) -> Dict[str, int]:
    return _extract_usage(usage_obj)

def normalize_model_id(model_id: str) -> str:
    """Normalize user-supplied model IDs to provider-prefixed IDs when needed."""
    if not model_id:
        return model_id
    if ":" in model_id:
        return model_id
    # Only assume OpenRouter when the model id looks like an OpenRouter spec (provider/model).
    # Otherwise, let pydantic-ai infer the provider from the model name.
    if settings.openrouter_api_key and "/" in model_id:
        return f"openrouter:{model_id}"
    return model_id

def format_markdown(text: str) -> str:
    """Pre-processes markdown to make LaTeX math look nicer and highlight sources."""
    if not text:
        return ""
    
    # 0. Highlight Sources: [Source: Note Name] or [vault note: Note Name] -> link to Obsidian
    def replace_source(match):
        note_ref = match.group(1).strip()
        note_name = note_ref
        header = None
        if " > " in note_ref:
            note_name, header = note_ref.split(" > ", 1)
            note_name = note_name.strip()
            header = header.strip()
        if settings.vault_path:
            vault_name = urllib.parse.quote(settings.vault_path.name)
            # Encode file path (allow / for nested paths)
            encoded_file = urllib.parse.quote(note_name, safe="/")
            if header:
                # Encode header completely (no safe characters) for proper Obsidian navigation
                encoded_header = urllib.parse.quote(header)
                file_param = f"{encoded_file}#{encoded_header}"
            else:
                file_param = encoded_file
            uri = f"obsidian://open?vault={vault_name}&file={file_param}"
            # Use the note name (and header if present) as the link label
            label = note_name if not header else f"{note_name} > {header}"
            return f"[{label}]({uri})"
        # Fallback when vault path isn't configured
        return note_name if not header else f"{note_name} > {header}"

    text = re.sub(
        r'\[(?:Source|Vault Note|vault note): (.*?)\]', 
        replace_source, 
        text
    )

    # 1. Block Math: $$ ... $$ -> ```latex ... ```
    text = re.sub(
        r'\$\$(.*?)\$\$', 
        r'```latex\n\1\n```', 
        text, 
        flags=re.DOTALL
    )
    
    # 2. Inline Math: $...$ -> `$ ... $`
    text = re.sub(
        r'(?<!\\)\$(?!\s)([^$\n]+?)(?<!\s)(?<!\\)\$', 
        r'`$\1$`', 
        text
    )
    
    return text

def render_markdown(text: str) -> None:
    """Render formatted markdown to the console using the shared theme."""
    console.print(Markdown(format_markdown(text)))

def _stringify_tool_args(args: Any) -> str:
    if args is None:
        return ""
    if isinstance(args, str):
        return args
    try:
        return json.dumps(args, ensure_ascii=True)
    except Exception:
        return str(args)

def _truncate(text: str, limit: int = 300) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."

async def stream_agent_output(agent, prompt: str) -> tuple[Optional[str], Dict[str, int]]:
    """
    Stream agent output while also rendering tool calls and reasoning parts.
    Returns the final output text if available.
    """
    try:
        from pydantic_ai import (
            AgentRunResultEvent,
            FunctionToolCallEvent,
            FunctionToolResultEvent,
            PartDeltaEvent,
            PartStartEvent,
            TextPartDelta,
            ThinkingPartDelta,
        )
    except Exception:
        result = await agent.run(prompt)
        render_markdown(str(result.output))
        usage = _extract_usage(getattr(result, "usage", None))
        return str(result.output), usage

    output_text = ""
    thinking_text = ""
    log_lines: list[str] = []

    def make_renderable():
        parts = []
        if log_lines:
            parts.append(Text("\n".join(log_lines), style="dim"))
        if thinking_text:
            parts.append(Text(f"thinking: {thinking_text}", style="dim"))
        parts.append(Markdown(format_markdown(output_text)))
        return Group(*parts)

    usage: Dict[str, int] = {}

    with Live(make_renderable(), refresh_per_second=12, console=console) as live:
        async for event in agent.run_stream_events(prompt):
            if isinstance(event, AgentRunResultEvent):
                if isinstance(event.result.output, str):
                    output_text = event.result.output
                    live.update(make_renderable())
                usage = _extract_usage(getattr(event.result, "usage", None))
                continue

            if isinstance(event, PartStartEvent):
                part_kind = getattr(event.part, "part_kind", None)
                content = getattr(event.part, "content", None)
                if part_kind == "text" and content:
                    output_text += content
                    live.update(make_renderable())
                elif part_kind == "thinking" and content:
                    thinking_text += content
                    live.update(make_renderable())
                continue

            if isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta):
                    if event.delta.content_delta:
                        output_text += event.delta.content_delta
                        live.update(make_renderable())
                elif isinstance(event.delta, ThinkingPartDelta):
                    if event.delta.content_delta:
                        thinking_text += event.delta.content_delta
                        live.update(make_renderable())
                continue

            if isinstance(event, FunctionToolCallEvent):
                tool_name = event.part.tool_name
                tool_args = _stringify_tool_args(event.part.args)
                if tool_args:
                    log_lines.append(f"tool call: {tool_name} {tool_args}")
                else:
                    log_lines.append(f"tool call: {tool_name}")
                live.update(make_renderable())
                continue

            if isinstance(event, FunctionToolResultEvent):
                result_text = getattr(event.result, "content", None)
                tool_name = getattr(event.result, "tool_name", None)
                if result_text:
                    result_str = _truncate(str(result_text))
                    if tool_name:
                        log_lines.append(f"tool result: {tool_name} {result_str}")
                    else:
                        log_lines.append(f"tool result: {result_str}")
                else:
                    log_lines.append(f"tool result: {event.tool_call_id}")
                live.update(make_renderable())
                continue

    return output_text, usage
