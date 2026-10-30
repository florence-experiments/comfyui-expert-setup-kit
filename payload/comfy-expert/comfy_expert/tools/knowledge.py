"""Knowledge pack lookup: markdown files in comfy_expert/knowledge (+ playbooks)."""
from __future__ import annotations

import re
from pathlib import Path

from . import tool, ToolError
from ..config import PKG_DIR

KB_DIR = PKG_DIR / "knowledge"
PB_DIR = KB_DIR / "playbooks"


def topics() -> dict[str, Path]:
    return {p.stem: p for p in sorted(KB_DIR.glob("*.md"))}


def playbooks() -> dict[str, Path]:
    return {p.stem: p for p in sorted(PB_DIR.glob("*.md"))}


def _sections(text: str) -> list[tuple[str, str]]:
    parts, title, buf = [], "intro", []
    for line in text.splitlines():
        if re.match(r"^#{1,3} ", line):
            if buf:
                parts.append((title, "\n".join(buf).strip()))
            title, buf = line.lstrip("# ").strip(), [line]
        else:
            buf.append(line)
    if buf:
        parts.append((title, "\n".join(buf).strip()))
    return parts


def _first_line(p: Path) -> str:
    for l in p.read_text(encoding="utf-8").splitlines():
        if l.strip() and not l.startswith("#"):
            return l.strip()[:160]
    return ""


@tool("kb_list", "List the built-in expert knowledge topics and playbooks.", {}, [], category="knowledge")
def kb_list():
    return {"topics": {k: _first_line(v) for k, v in topics().items()},
            "playbooks": {k: _first_line(v) for k, v in playbooks().items()}}


@tool("kb_read", "Read a knowledge topic (optionally only the section whose heading contains 'section').",
      {"topic": {"type": "string"}, "section": {"type": "string", "default": ""}}, ["topic"], category="knowledge")
def kb_read(topic: str, section: str = ""):
    all_ = {**topics(), **{f"playbook_{k}": v for k, v in playbooks().items()}, **playbooks()}
    p = all_.get(topic) or all_.get(topic.replace(".md", ""))
    if not p:
        raise ToolError(f"No topic '{topic}'. Topics: {sorted(topics())}")
    text = p.read_text(encoding="utf-8")
    if section:
        secs = [s for s in _sections(text) if section.lower() in s[0].lower()]
        if secs:
            text = "\n\n".join(s[1] for s in secs)
    return {"topic": p.stem, "text": text[:14000], "truncated": len(text) > 14000}


@tool("kb_search", "Search the built-in knowledge pack (ComfyUI, model families, settings, sites, AMD tips) for a phrase.",
      {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 4}}, ["query"], category="knowledge")
def kb_search(query: str, max_results: int = 4):
    words = [w for w in re.findall(r"[a-z0-9_.\-]+", query.lower()) if len(w) > 1]
    if not words:
        raise ToolError("empty query")
    scored = []
    for name, p in {**topics(), **playbooks()}.items():
        for title, body in _sections(p.read_text(encoding="utf-8")):
            low = body.lower()
            score = sum(low.count(w) for w in words) + 5 * sum(w in title.lower() for w in words)
            if all(w in low for w in words):
                score *= 2
            if score:
                scored.append((score, name, title, body))
    scored.sort(key=lambda x: -x[0])
    return {"results": [{"topic": n, "section": t, "text": b[:2500]} for _s, n, t, b in scored[: int(max_results or 4)]]}


@tool("get_playbook",
      "Get the step-by-step procedure for a common job: explain_workflow, remake_workflow, find_models, fix_missing_nodes, "
      "build_from_template, troubleshoot, compare_models, image_to_prompt.",
      {"name": {"type": "string"}}, ["name"], category="knowledge")
def get_playbook(name: str):
    p = playbooks().get(name)
    if not p:
        raise ToolError(f"No playbook '{name}'. Available: {sorted(playbooks())}")
    return {"playbook": name, "steps": p.read_text(encoding="utf-8")}
