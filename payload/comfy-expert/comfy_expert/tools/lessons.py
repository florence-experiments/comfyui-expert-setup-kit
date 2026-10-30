"""Prompt Artist lessons: what went wrong in a generation, why, and the fix that worked.

Lessons are saved as 'tentative' when fix mode suggests them, and become 'confirmed' only when the user says the
fix worked (the "This fixed it" button, or a reply like "that fixed it"). Fixes that the user says failed are marked
'failed' and never shown to the model again. Stored as JSON in the app folder (data/prompt_lessons.json by default),
de-duplicated and capped; confirmed and most-used lessons come first."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from . import tool
from ..config import APP_DIR, load_config

CAP = 200
FIELDS = ("family", "checkpoint", "symptom", "cause", "fix")
_LOCK = threading.Lock()
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "is", "was", "were", "too", "with", "for", "it", "its",
         "into", "at", "by", "be", "not", "no", "from", "as", "are", "this", "that", "very"}


def path() -> Path:
    p = (load_config().get("vision") or {}).get("lessons_file") or ""
    return Path(p) if p else APP_DIR / "data" / "prompt_lessons.json"


def family_key(text: str) -> str:
    """Normalise a family name or checkpoint file to the classifier's family label."""
    from .imageprompt import FAMILY_RULES
    low = (text or "").lower()
    for pat, fam in FAMILY_RULES:
        if re.search(pat, low):
            return fam
    return (text or "").strip() or "any"


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in _STOP and len(w) > 1}


def _similar(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def load() -> list[dict]:
    p = path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("lessons", []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "lessons": items}, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _rank(l: dict) -> tuple:
    return ({"confirmed": 2, "tentative": 1}.get(l.get("status"), 0), l.get("confirmations", 0), l.get("seen", 1),
            l.get("updated", 0))


def _cap(items: list[dict]) -> list[dict]:
    items.sort(key=_rank, reverse=True)
    return items[:CAP]


def add(lesson: dict, session: str = "") -> dict | None:
    """Add a tentative lesson, or merge it into a near-duplicate (same family, similar symptom and fix)."""
    l = {k: str(lesson.get(k) or "").strip()[:400] for k in FIELDS}
    if not l["symptom"] or not l["fix"]:
        return None
    l["family"] = family_key(l["family"] or l["checkpoint"])
    now = time.time()
    with _LOCK:
        items = load()
        for old in items:
            if old.get("family") == l["family"] and _similar(old["symptom"], l["symptom"]) >= 0.5 \
                    and (_similar(old["fix"], l["fix"]) >= 0.3 or _similar(old["cause"], l["cause"]) >= 0.5):
                old["seen"] = old.get("seen", 1) + 1
                old["updated"] = now
                if old.get("status") == "failed":            # proposed again: give it another chance
                    old.update(status="tentative", cause=l["cause"] or old["cause"], fix=l["fix"])
                if l["checkpoint"] and l["checkpoint"] not in old.get("checkpoints", []):
                    old.setdefault("checkpoints", []).append(l["checkpoint"])
                if session:
                    old["session"] = session
                _save(_cap(items))
                return old
        new = {"id": uuid.uuid4().hex[:8], **l, "checkpoints": [l["checkpoint"]] if l["checkpoint"] else [],
               "status": "tentative", "seen": 1, "confirmations": 0, "fails": 0, "created": now, "updated": now,
               "session": session}
        new.pop("checkpoint")
        items.append(new)
        _save(_cap(items))
        return new


def _mark(ids: list[str], status: str) -> list[dict]:
    done = []
    with _LOCK:
        items = load()
        for l in items:
            if l.get("id") in ids:
                if status == "confirmed":
                    l["confirmations"] = l.get("confirmations", 0) + 1
                    l["status"] = "confirmed"
                else:
                    l["fails"] = l.get("fails", 0) + 1
                    if l.get("status") != "confirmed" or l["fails"] > l.get("confirmations", 0):
                        l["status"] = "failed"
                l["updated"] = time.time()
                done.append(l)
        _save(_cap(items))
    return done


def confirm(ids: list[str]) -> list[dict]:
    return _mark(ids, "confirmed")


def reject(ids: list[str]) -> list[dict]:
    return _mark(ids, "failed")


def relevant(family: str = "", checkpoint: str = "", limit: int = 10) -> list[dict]:
    """Lessons to show the model: never failed ones; this family (or checkpoint) first, confirmed and most used first.
    Without a family: confirmed lessons from every family, then tentative ones."""
    items = [l for l in load() if l.get("status") in ("confirmed", "tentative")]
    fam = family_key(family or checkpoint) if (family or checkpoint) else ""
    if fam:
        items = [l for l in items if l.get("family") in (fam, "any") or (checkpoint and checkpoint in l.get("checkpoints", []))]
        items.sort(key=lambda l: (bool(checkpoint and checkpoint in l.get("checkpoints", [])),) + _rank(l), reverse=True)
    else:
        items.sort(key=_rank, reverse=True)
    return items[:limit]


def as_text(items: list[dict]) -> str:
    if not items:
        return "(none yet)"
    out = []
    for l in items:
        ck = f" [{', '.join(l['checkpoints'][:2])}]" if l.get("checkpoints") else ""
        tag = f"confirmed x{l.get('confirmations', 1)}" if l.get("status") == "confirmed" else "tentative"
        out.append(f"- ({tag}) {l['family']}{ck}: {l['symptom']} -> cause: {l['cause'] or '?'} -> fix: {l['fix']}")
    return "\n".join(out)


LESSONS_BLOCK_RE = re.compile(r"```\s*lessons\s*\n(.*?)(?:```|$)", re.S | re.I)


def parse_block(text: str) -> tuple[str, list[dict]]:
    """Split the model's ```lessons JSON block off the answer. Returns (answer without block, lessons)."""
    m = LESSONS_BLOCK_RE.search(text or "")
    if not m:
        return text, []
    found: list[dict] = []
    raw = m.group(1).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        found = [d for d in data if isinstance(d, dict)]
    except ValueError:
        for obj in re.findall(r"\{.*?\}", raw, re.S):
            try:
                found.append(json.loads(obj))
            except ValueError:
                pass
    head = text[:m.start()].rstrip()
    head = re.sub(r"\n#{2,4}\s*Lessons\s*$", "", head).rstrip()
    return head, found


@tool("prompt_lessons",
      "List what Prompt Artist has learned from the user's fixed generations (symptom -> cause -> fix), confirmed first. "
      "Optionally filter by model family or checkpoint file.",
      {"family": {"type": "string", "default": "", "description": "e.g. Pony, Illustrious, waiIllustriousSDXL_v170.safetensors"},
       "limit": {"type": "integer", "default": 20}}, [], category="image")
def prompt_lessons(family: str = "", limit: int = 20):
    items = relevant(family, "", int(limit or 20))
    return {"file": str(path()), "count": len(load()), "lessons": items}
