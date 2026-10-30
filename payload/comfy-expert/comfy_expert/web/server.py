"""Local browser chat UI (FastAPI). Binds to 127.0.0.1 by default."""
from __future__ import annotations

import json
import re
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ..agent import Agent, Session
from ..chats import ChatStore, make_title
from ..config import APP_DIR, load_config

STATIC = Path(__file__).resolve().parent / "static"
UPLOADS = APP_DIR / "cache" / "uploads"
MAX_SAVED_RESULT = 6000     # characters of each tool result kept in the saved chat's screen history


def _saved_event(ev: dict) -> dict | None:
    """The part of an agent event worth keeping to redraw the chat later (no token deltas / reasoning)."""
    t = ev.get("type")
    if t == "confirm" and len(json.dumps(ev.get("preview"), default=str)) > MAX_SAVED_RESULT:
        return {**ev, "preview": {"saved_preview": json.dumps(ev.get("preview"), default=str)[:MAX_SAVED_RESULT]}}
    if t in ("assistant", "status", "final", "error", "confirm", "tool_call"):
        return {k: v for k, v in ev.items() if k != "items"}
    if t == "tool_result":
        res = ev.get("result")
        txt = json.dumps(res, ensure_ascii=False, default=str)
        if len(txt) > MAX_SAVED_RESULT:
            res = {"ok": res.get("ok", True) if isinstance(res, dict) else True,
                   "saved_preview": txt[:MAX_SAVED_RESULT] + " ... [cut in the saved chat]"}
        return {"type": t, "id": ev.get("id"), "name": ev.get("name"), "short": ev.get("short"), "result": res}
    return None


def create_app(store: ChatStore | None = None, agent: Agent | None = None) -> FastAPI:
    cfg = load_config()
    agent = agent or Agent(cfg)
    store = store or ChatStore()
    try:
        store.import_legacy()          # one-time copy of chats saved by the old version (cache/sessions)
    except Exception as e:  # pragma: no cover
        print(f"Could not import old chats: {e}")
    sessions: dict[str, Session] = {}
    locks: dict[str, threading.Lock] = {}
    app = FastAPI(title="ComfyUI Expert")

    def _cache(s: Session) -> Session:
        sessions[s.id] = s
        locks.setdefault(s.id, threading.Lock())
        return s

    def get_session(sid: str | None, create: bool = True) -> Session:
        if sid and sid in sessions:
            return sessions[sid]
        if sid and store.exists(sid):
            return _cache(store.load(sid))
        if not create:
            raise HTTPException(404, "unknown chat")
        s = Session()
        while s.id in sessions or store.exists(s.id):
            s = Session()
        return _cache(s)

    def save(s: Session) -> None:
        try:
            store.save(s)
        except OSError as e:  # pragma: no cover
            print(f"Could not save chat {s.id}: {e}")

    def stream(session: Session, make_events, user_entry=None):
        """Run one agent turn. The chat is saved when the message arrives and again when the turn ends
        (also if the browser tab is closed half-way)."""
        lock = locks[session.id]
        if not lock.acquire(blocking=False):
            def busy():
                yield json.dumps({"type": "error", "text": "This chat is still working on the previous message."}) + "\n"
            return StreamingResponse(busy(), media_type="application/x-ndjson")
        try:
            events = make_events()
            if user_entry is not None:
                session.display.append(user_entry() if callable(user_entry) else user_entry)
            save(session)
        except BaseException:
            lock.release()
            raise
        entry = {"role": "assistant", "ts": time.time(), "events": [], "text": ""}

        def gen():
            try:
                try:
                    yield json.dumps({"type": "session", "id": session.id, "title": session.title}) + "\n"
                    for ev in events:
                        kept = _saved_event(ev)
                        if kept:
                            entry["events"].append(kept)
                            if ev["type"] == "final":
                                entry["text"] = ev.get("text") or ""
                                if ev.get("pa"):
                                    entry["pa"] = ev["pa"]
                        yield json.dumps(ev, ensure_ascii=False, default=str) + "\n"
                except Exception as e:  # pragma: no cover
                    err = {"type": "error", "text": f"{type(e).__name__}: {e}"}
                    entry["events"].append(err)
                    yield json.dumps(err) + "\n"
                if session.pending:
                    yield json.dumps({"type": "waiting_confirm"}) + "\n"
                yield json.dumps({"type": "done"}) + "\n"
            finally:
                if entry["events"]:
                    session.display.append(entry)
                save(session)
                lock.release()
        return StreamingResponse(gen(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def summary(s: Session) -> dict:
        return {"id": s.id, "title": s.title or "New chat", "mode": store.mode_of(s), "created": s.created,
                "updated": s.updated, "pending": bool(s.pending), "pa_pending": bool((s.pa or {}).get("pending")),
                "busy": bool(locks.get(s.id) and locks[s.id].locked())}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/info")
    def info():
        import requests
        out = {"name": "ComfyUI Expert", "llm_url": cfg["llm"]["base_url"], "comfy_url": cfg["comfyui"]["url"]}
        try:
            out["model"] = agent.model()
            out["n_ctx"] = agent.server_context()
        except Exception as e:
            out["model"] = None
            out["llm_error"] = str(e)
        try:
            st = requests.get(cfg["comfyui"]["url"] + "/system_stats", timeout=3).json()
            dev = (st.get("devices") or [{}])[0]
            out["comfy"] = {"version": st.get("system", {}).get("comfyui_version"), "device": dev.get("name"),
                            "vram_free_gb": round((dev.get("vram_free") or 0) / 2**30, 1)}
        except Exception:
            out["comfy"] = None
        return out

    @app.post("/api/chat")
    async def chat(req: Request):
        body = await req.json()
        msg = (body.get("message") or "").strip()
        if not msg:
            raise HTTPException(400, "empty message")
        s = get_session(body.get("session_id"))
        prepared: dict = {}

        def events():
            text, files = store.adopt_files(s, msg)     # keep the chat's pictures / workflows with the chat
            prepared.update(text=text, files=files)
            if not s.title:
                s.title = make_title(msg)
            return agent.chat(s, text)

        def user_entry():
            return {"role": "user", "ts": time.time(), "text": prepared.get("text", msg), "files": prepared.get("files", [])}
        return stream(s, events, user_entry)

    @app.post("/api/confirm")
    async def confirm(req: Request):
        body = await req.json()
        s = get_session(body.get("session_id"), create=False)
        ok = bool(body.get("approved"))
        entry = {"role": "decision", "ts": time.time(), "approved": ok} if s.pending else None
        return stream(s, lambda: agent.resume(s, ok), entry)

    @app.post("/api/new")
    def new():
        s = get_session(None)
        return {"session_id": s.id}

    # ------------------------------------------------------------- saved chats
    @app.get("/api/chats")
    def list_chats(q: str = ""):
        return {"chats": store.list(q)}

    @app.post("/api/chats")
    async def create_chat(req: Request):
        try:
            body = await req.json()
        except Exception:
            body = {}
        s = _cache(store.create((body or {}).get("title") or ""))
        return summary(s)

    @app.get("/api/chats/{cid}")
    def get_chat(cid: str):
        if cid not in sessions and not store.exists(cid):
            raise HTTPException(404, "unknown chat")
        s = get_session(cid, create=False)
        return {**summary(s), "display": s.display}

    @app.patch("/api/chats/{cid}")
    async def rename_chat(cid: str, req: Request):
        body = await req.json()
        title = (body.get("title") or "").strip()
        if not title:
            raise HTTPException(400, "empty title")
        if cid not in sessions and not store.exists(cid):
            raise HTTPException(404, "unknown chat")
        s = get_session(cid, create=False)
        if locks[s.id].locked():           # saved when the running answer finishes
            s.title, s.title_custom = title[:120], True
        else:
            store.rename(s, title)
        return summary(s)

    @app.delete("/api/chats/{cid}")
    def delete_chat(cid: str):
        lock = locks.get(cid)
        if lock and not lock.acquire(blocking=False):
            raise HTTPException(409, "This chat is still answering. Wait for it to finish, then delete it.")
        try:
            sessions.pop(cid, None)
            try:
                res = store.delete(cid)
            except KeyError:
                if lock is None:
                    raise HTTPException(404, "unknown chat")
                res = {"id": cid, "erased_files": 0}     # never saved (empty new chat)
            return {"ok": True, **res}
        finally:
            if lock:
                lock.release()
                locks.pop(cid, None)

    @app.get("/api/chats/{cid}/files/{name}")
    def chat_file(cid: str, name: str):
        try:
            return FileResponse(store.file_path(cid, name))
        except KeyError:
            raise HTTPException(404, "not found")

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        name = re.sub(r"[^\w.\-() ]", "_", Path(file.filename or "upload").name)[:120]
        low = name.lower()
        if not low.endswith((".json", ".png", ".webp", ".jpg", ".jpeg", ".bmp", ".gif")):
            raise HTTPException(400, "Only .json workflows or .png / .jpg / .webp / .bmp / .gif images")
        data = await file.read()
        if len(data) > 60 * 2**20:
            raise HTTPException(400, "File too large")
        store.uploads.mkdir(parents=True, exist_ok=True)
        p = store.uploads / f"{time.strftime('%Y%m%d-%H%M%S')}_{name}"
        p.write_bytes(data)
        kind = "workflow" if low.endswith(".json") else "image"
        if low.endswith(".png"):
            from ..tools.wfcore import _png_text_chunks
            if "workflow" in _png_text_chunks(data):
                kind = "image+workflow"      # a ComfyUI output: usable as an image and as a workflow
        return {"path": str(p), "name": name, "kind": kind}

    return app


def main(host: str | None = None, port: int | None = None, open_browser: bool = True) -> int:
    import uvicorn
    cfg = load_config()
    host = host or cfg["ui"].get("host") or "127.0.0.1"
    port = int(port or cfg["ui"].get("port") or 7860)
    app = create_app()
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    print(f"ComfyUI Expert web UI: {url}  (Ctrl+C to stop)")
    if open_browser and cfg["ui"].get("open_browser", True):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
