"""Saved chats: one JSON file per chat in data/chats/<id>.json, its pictures in data/chats/<id>/.

Each file keeps what the screen shows ("display") and everything the agent needs to carry on
(the full model message list, Prompt Artist state, loop guards, a pending Yes/No question).
Writes are atomic (temp file + rename). Deleting a chat securely erases it: every file is
overwritten with random bytes, emptied, renamed to a random name and then removed.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .agent import Session
from .config import APP_DIR

CHATS_DIR = APP_DIR / "data" / "chats"
LEGACY_DIR = APP_DIR / "cache" / "sessions"
UPLOADS = APP_DIR / "cache" / "uploads"
IMPORT_MARKER = ".imported-legacy.json"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
FILE_REF_RE = re.compile(r"^((?:Image|Reference|Workflow) file):[ \t]*(\S.*?)[ \t]*$", re.M)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
_STATE = ("evidence", "failed", "calls", "gated_done", "self_checked", "pending", "pa")


def valid_id(cid: str) -> bool:
    return bool(cid and ID_RE.match(cid))


def secure_wipe_file(path: Path) -> bool:
    """One random-overwrite pass + fsync, truncate + fsync, rename to a random name, remove.
    Same method as HomeAI. Returns False if the file did not exist."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass
    with open(path, "r+b", buffering=0) as f:
        left = size
        while left > 0:
            n = min(left, 1 << 20)
            f.write(os.urandom(n))
            left -= n
        f.flush()
        os.fsync(f.fileno())
        f.seek(0)
        f.truncate(0)
        f.flush()
        os.fsync(f.fileno())
    rnd = path.parent / ("~" + secrets.token_hex(16) + ".del")
    os.replace(path, rnd)
    os.remove(rnd)
    return True


def atomic_write_text(path: Path, text: str) -> None:
    """Write to a temp file in the same folder, fsync, then rename over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for i in range(6):          # Windows: the target can be briefly locked by a reader / antivirus
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == 5:
                    raise
                time.sleep(0.05 * (i + 1))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def make_title(text: str) -> str:
    """Short title from the first user message (Prompt Artist messages get the picture's name)."""
    t = text or ""
    img = re.search(r"(?:Image|Workflow) file:[ \t]*(\S.*?)[ \t]*$", t, re.M)
    t = FILE_REF_RE.sub("", t)
    t = re.sub(r"\n\n\[(?:ComfyUI Expert note|Prompt Artist).*", "", t, flags=re.S)
    pa_fix = bool(re.match(r"\s*prompt artist fix", t, re.I))
    pa = bool(re.match(r"\s*prompt artist", t, re.I))
    if pa:
        t = re.sub(r"(?i)^\s*prompt artist( fix)?:?\s*", "", t)
        t = re.sub(r"(?i)analy[sz]e this image and write the best prompt to recreate it\.?|"
                   r"here is the image i generated[^\n]*", "", t)
        t = re.sub(r"(?im)^note:\s*", "", t)
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    first = lines[0] if lines else ""
    if pa:
        name = ""
        if img:
            name = _basename(img.group(1)).rsplit(".", 1)[0]
            name = re.sub(r"^\d{8}-\d{6}_", "", name)
        head = ("Prompt Artist fix: " if pa_fix else "Prompt Artist: ") + (name or "picture")
        first = head + (" – " + first if first else "")
    elif not first and img:
        first = "Workflow " + _basename(img.group(1))
    first = re.sub(r"\s+", " ", first).strip() or "New chat"
    return first if len(first) <= 60 else first[:57].rstrip() + "…"


def file_url(cid: str, name: str) -> str:
    return f"/api/chats/{cid}/files/{name}"


class ChatStore:
    def __init__(self, root: Path | None = None, legacy: Path | None = None, uploads: Path | None = None):
        self.root = Path(root or CHATS_DIR)
        self.legacy = Path(legacy) if legacy else LEGACY_DIR
        self.uploads = Path(uploads) if uploads else UPLOADS
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ paths
    def path(self, cid: str) -> Path:
        if not valid_id(cid):
            raise KeyError(cid)
        return self.root / f"{cid}.json"

    def files_dir(self, cid: str) -> Path:
        if not valid_id(cid):
            raise KeyError(cid)
        return self.root / cid

    def exists(self, cid: str) -> bool:
        return valid_id(cid) and self.path(cid).is_file()

    # ------------------------------------------------------------ session <-> record
    @staticmethod
    def mode_of(s: Session) -> str:
        if s.pa or any(d.get("pa") for d in getattr(s, "display", []) if isinstance(d, dict)):
            return "prompt_artist"
        return "normal"

    def record(self, s: Session) -> dict:
        rec = {"version": 1, "id": s.id, "title": s.title or "New chat", "title_custom": s.title_custom,
               "created": s.created, "updated": s.updated or time.time(), "mode": self.mode_of(s),
               "display": s.display, "messages": s.messages}
        rec["state"] = {k: getattr(s, k) for k in _STATE}
        return rec

    @staticmethod
    def session(rec: dict) -> Session:
        s = Session(id=rec["id"])
        s.title = rec.get("title") or ""
        s.title_custom = bool(rec.get("title_custom"))
        s.created = float(rec.get("created") or time.time())
        s.updated = float(rec.get("updated") or s.created)
        s.messages = list(rec.get("messages") or [])
        s.display = list(rec.get("display") or [])
        st = rec.get("state") or {}
        for k in _STATE:
            if k in st and st[k] is not None:
                setattr(s, k, st[k])
        s.blocked = 0
        return s

    # ------------------------------------------------------------ CRUD
    def save(self, s: Session, touch: bool = True) -> Path:
        with self.lock:
            if touch or not s.updated:
                s.updated = time.time()
            p = self.path(s.id)
            atomic_write_text(p, json.dumps(self.record(s), ensure_ascii=False, indent=1, default=str))
            return p

    def create(self, title: str = "") -> Session:
        s = Session()
        while self.exists(s.id):
            s = Session()
        if title.strip():
            s.title, s.title_custom = title.strip()[:120], True
        self.save(s)
        return s

    def load_record(self, cid: str) -> dict:
        p = self.path(cid)
        if not p.is_file():
            raise KeyError(cid)
        return json.loads(p.read_text(encoding="utf-8"))

    def load(self, cid: str) -> Session:
        return self.session(self.load_record(cid))

    def rename(self, s: Session, title: str) -> Session:
        title = re.sub(r"\s+", " ", title or "").strip()[:120]
        if not title:
            raise ValueError("empty title")
        s.title, s.title_custom = title, True
        self.save(s, touch=False)
        return s

    def delete(self, cid: str) -> dict:
        """Secure erase of the chat file and every file in its picture folder."""
        with self.lock:
            p = self.path(cid)
            d = self.files_dir(cid)
            if not p.is_file() and not d.is_dir():
                raise KeyError(cid)
            n = 0
            if d.is_dir():
                for f in sorted(d.rglob("*"), key=lambda x: -len(x.parts)):
                    if f.is_file() and not f.is_symlink():
                        n += secure_wipe_file(f)
                    elif f.is_dir():
                        f.rmdir()
                d.rmdir()
            n += secure_wipe_file(p)
            for tmp in self.root.glob(f".{cid}.json.*.tmp"):
                secure_wipe_file(tmp)
            return {"id": cid, "erased_files": n}

    def list(self, query: str = "") -> list[dict]:
        q = (query or "").strip().lower()
        out = []
        for p in self.root.glob("*.json"):
            if p.name.startswith("."):
                continue
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            disp = rec.get("display") or []
            if q:
                hay = (rec.get("title") or "") + "\n" + "\n".join(str(d.get("text") or "") for d in disp)
                if q not in hay.lower():
                    continue
            thumb = next((f["url"] for d in disp if d.get("role") == "user"
                          for f in d.get("files") or [] if f.get("kind") == "image"), None)
            last = next((d.get("text") for d in reversed(disp) if d.get("text")), "")
            out.append({"id": rec.get("id"), "title": rec.get("title") or "New chat", "mode": rec.get("mode", "normal"),
                        "created": rec.get("created"), "updated": rec.get("updated"),
                        "turns": sum(1 for d in disp if d.get("role") == "user"),
                        "preview": re.sub(r"\s+", " ", re.sub(r"[#*`>|]", "", str(last)))[:120], "thumb": thumb,
                        "imported": bool(rec.get("imported_from"))})
        out.sort(key=lambda r: r.get("updated") or 0, reverse=True)
        return out

    # ------------------------------------------------------------ pictures / uploaded files
    def adopt_files(self, s: Session, text: str, move: bool = True) -> tuple[str, list[dict]]:
        """Copy files referenced in a user message ('Image file: ...') into the chat's folder and point the
        message at the copy, so the chat keeps its pictures. Fresh uploads (cache/uploads) are moved there."""
        files: list[dict] = []
        d = self.files_dir(s.id)

        def repl(m: re.Match) -> str:
            label, raw = m.group(1), m.group(2).strip().strip('"')
            src = Path(raw)
            try:
                inside = src.resolve().parent == d.resolve()
            except OSError:
                inside = False
            dst = d / src.name
            if not inside:
                if not src.is_file():
                    if dst.is_file():          # already moved by an earlier message
                        inside = True
                    else:
                        files.append({"name": src.name, "kind": _kind(src.name), "missing": True})
                        return m.group(0)
                if not inside:
                    d.mkdir(parents=True, exist_ok=True)
                    if dst.exists() and not _same(src, dst):
                        dst = d / f"{secrets.token_hex(3)}_{src.name}"
                    if not dst.exists():
                        from_uploads = _under(src, self.uploads)
                        if move and from_uploads:
                            shutil.move(str(src), str(dst))
                        else:
                            shutil.copy2(src, dst)
            else:
                dst = src
            files.append({"name": dst.name, "kind": _kind(dst.name), "url": file_url(s.id, dst.name)})
            return f"{label}: {dst}"

        return FILE_REF_RE.sub(repl, text or ""), files

    def file_path(self, cid: str, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name.startswith(".") or ".." in name:
            raise KeyError(name)
        p = self.files_dir(cid) / name
        if not p.is_file():
            raise KeyError(name)
        return p

    # ------------------------------------------------------------ old chats (cache/sessions, before saved chats)
    def import_legacy(self) -> list[str]:
        """One-time copy of chats the old version left in cache/sessions. Originals are not touched."""
        marker = self.root / IMPORT_MARKER
        done: dict = {}
        if marker.is_file():
            try:
                done = json.loads(marker.read_text(encoding="utf-8"))
            except ValueError:
                done = {}
        if not self.legacy.is_dir():
            return []
        new = []
        for p in sorted(self.legacy.glob("*.json")):
            if p.stem in done or not valid_id(p.stem):
                continue
            try:
                old = json.loads(p.read_text(encoding="utf-8"))
                msgs = old.get("messages") or []
                if not any(m.get("role") == "user" for m in msgs):
                    done[p.stem] = "empty"
                    continue
                cid = p.stem if not self.exists(p.stem) else p.stem + "-old"
                s = Session(id=cid)
                s.created = float(old.get("created") or p.stat().st_mtime)
                s.updated = p.stat().st_mtime
                s.messages = msgs
                for m in s.messages:
                    if m.get("role") == "user" and m.get("content"):
                        m["content"], _ = self.adopt_files(s, m["content"], move=False)
                s.display, s.pa = legacy_display(s)
                s.evidence = [m.get("content") or "" for m in msgs if m.get("role") in ("user", "tool")]
                first = next((d["text"] for d in s.display if d.get("role") == "user"), "")
                s.title = make_title(first) if first else (old.get("title") or "Recovered chat")
                rec_path = self.save(s, touch=False)
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
                rec["imported_from"] = str(p)
                atomic_write_text(rec_path, json.dumps(rec, ensure_ascii=False, indent=1, default=str))
                done[p.stem] = cid
                new.append(cid)
            except Exception as e:  # never let one bad old file stop the app
                done[p.stem] = f"error: {type(e).__name__}: {e}"
        atomic_write_text(marker, json.dumps(done, indent=1))
        return new


def legacy_display(s: Session) -> tuple[list[dict], dict]:
    """Rebuild the visible conversation from an old message list (user text without the helper notes,
    tool steps and final answers as the same events the live chat shows) and the Prompt Artist state."""
    disp: list[dict] = []
    pa: dict = {}
    cur: dict | None = None
    for m in s.messages:
        role, c = m.get("role"), m.get("content") or ""
        if role == "user":
            if c.startswith("[self-check") or c.startswith("(system)"):
                if cur is not None:     # the draft answer that was sent back for checking: hide it
                    cur["events"] = [e for e in cur["events"] if e["type"] != "final"]
                    cur["text"] = ""
                continue
            text = re.split(r"\n\n\[(?:ComfyUI Expert note|Prompt Artist)", c, maxsplit=1)[0]
            files = []
            for _label, raw in FILE_REF_RE.findall(text):
                fp = Path(raw.strip())
                if fp.is_file():
                    files.append({"name": fp.name, "kind": _kind(fp.name), "url": file_url(s.id, fp.name)})
            disp.append({"role": "user", "ts": s.created, "text": text.strip(), "files": files})
            if c.lower().startswith("prompt artist:"):
                im = re.search(r"Image file:\s*(.+?)\s*$", c, re.M)
                pa = {"reference": im.group(1).strip()} if im else {}
            cur = None
        elif role == "assistant":
            if cur is None:
                cur = {"role": "assistant", "ts": s.created, "text": "", "events": []}
                disp.append(cur)
            if c and m.get("tool_calls"):
                cur["events"].append({"type": "assistant", "text": c})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args) if args.strip() else {}
                    except ValueError:
                        args = {"raw": args}
                cur["events"].append({"type": "tool_call", "id": tc.get("id"), "name": fn.get("name", ""), "args": args})
            if c and not m.get("tool_calls"):
                cur["events"].append({"type": "final", "text": c})
                cur["text"] = c
                if "reference" in pa and re.search(r"Prompt for|Corrected prompt", c):
                    pa["answer"] = c
        elif role == "tool" and cur is not None:
            ok = not re.search(r'"ok":\s*false', c[:300])
            cur["events"].append({"type": "tool_result", "id": m.get("tool_call_id"), "name": m.get("name", ""),
                                  "short": "saved result" if ok else "error",
                                  "result": {"ok": ok, "saved_preview": c[:6000]}})
    disp = [d for d in disp if d["role"] == "user" or d.get("events")]
    return disp, (pa if pa.get("reference") else {})


def _basename(path: str) -> str:
    """File name from a Windows or POSIX path."""
    return re.split(r"[\\/]", path.strip().strip('"'))[-1]


def _kind(name: str) -> str:
    return "image" if name.lower().endswith(IMAGE_EXT) else "workflow"


def _under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _same(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False
