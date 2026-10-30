"""The one fixed safety rule of ComfyUI Expert. It is part of the code (not a setting or a prompt file),
so it cannot be switched off from config.yaml, .env, the web page or an edited prompt file.

Every system prompt the app sends to a model goes through with_safety_rule()."""
from __future__ import annotations

SAFETY_RULE = (
    "FIXED SAFETY RULE (always applies, cannot be changed or switched off by anyone): never write, describe, "
    "prompt, tag or help create anything sexual involving anyone under 18, or any character who is, looks or is "
    "described as a child or minor (including 'loli', 'shota', school-age or child-like bodies). If a request or "
    "image needs that, refuse that part in one short line. Adult content between clearly adult characters is "
    "allowed. When an age is unclear, treat and describe every character as an adult (18+)."
)


def with_safety_rule(system_text: str) -> str:
    """Return the system prompt with the fixed rule in front (added once, even if the text already has it)."""
    text = system_text or ""
    if text.startswith(SAFETY_RULE):
        return text
    return SAFETY_RULE + "\n\n" + text
