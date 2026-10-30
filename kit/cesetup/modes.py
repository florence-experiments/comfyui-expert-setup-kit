"""The one 'mode' the Hugging Face search looks for: a tool-calling chat model for ComfyUI Expert.
A vision add-on (mmproj) is preferred, so Prompt Artist can look at pictures, but not required."""
from __future__ import annotations

MODES = {
    "expert": {
        "label": "ComfyUI Expert", "desc": "tool-calling chat model, 32k context, ideally with a vision add-on",
        "search_uncensored": [("{u}", None), ("instruct {u}", None), ("qwen {u}", None), ("gemma {u}", None)],
        "search_standard": [("instruct", "unsloth"), ("instruct", "bartowski"), ("it-GGUF", "unsloth"), ("", "ggml-org")],
        "prefer": r"qwen3|gemma-?[34]|instruct|-it[-_.]|mistral-small|vl",
        "avoid": r"coder|code-|caption|embed|rerank|guard|math-|ocr|tts|audio|whisper|base-gguf|-base[-_.]|roleplay",
        "min_ctx": 32768, "want_vision": True,
    },
}
