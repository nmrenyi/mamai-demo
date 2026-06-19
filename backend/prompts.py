"""Prompt assembly — faithful to the deployed app + eval (shared/prompts.py).

Single-turn reduces exactly to the eval's _format_gemma_it:
    <start_of_turn>user
    {system}

    {user}<end_of_turn>
    <start_of_turn>model

Gemma has no system role, so the system prompt is folded into the first user
turn. Retrieved context is injected into the LATEST user turn using the deployed
labels (RELEVANT CONTEXT FROM MEDICAL GUIDELINES: / Question:).
"""

from pathlib import Path

from backend import config

SYSTEM_PROMPT = Path(config.SYSTEM_PROMPT_FILE).read_text(encoding="utf-8").rstrip("\n")


def _inject_context(user_text: str, context: str) -> str:
    """Wrap a user turn with retrieved context, exactly as build_rag_open_messages."""
    if not context:
        return user_text
    return f"{config.CONTEXT_LABEL}\n{context}\n\n{config.QUESTION_LABEL} {user_text}"


def build_prompt(history: list[dict], context: str) -> str:
    """Build a Gemma IT prompt string for llama-server's /completion endpoint.

    `history` is [{role: 'user'|'assistant', content: str}, ...] ending on a user
    turn. `context` (may be "") is injected into that final user turn only.
    """
    if not history or history[-1]["role"] != "user":
        raise ValueError("history must end with a user turn")

    parts = []
    last = len(history) - 1
    for i, turn in enumerate(history):
        role = turn["role"]
        content = turn["content"]
        if role == "user":
            if i == last:
                content = _inject_context(content, context)
            # Fold the system prompt into the FIRST user turn (Gemma convention).
            if i == 0:
                content = f"{SYSTEM_PROMPT}\n\n{content}"
            parts.append(f"<start_of_turn>user\n{content}<end_of_turn>\n")
        else:  # assistant
            parts.append(f"<start_of_turn>model\n{content}<end_of_turn>\n")
    parts.append("<start_of_turn>model\n")
    return "".join(parts)
