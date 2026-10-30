"""Saved chats: storage, secure delete, atomic writes, restore into the agent, and the HTTP API."""
import json
import os
import socket
import threading
import time

import pytest
import requests

from comfy_expert import chats as chats_mod
from comfy_expert.agent import Agent, Session
from comfy_expert.chats import ChatStore, make_title, secure_wipe_file


class Scripted(Agent):
    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.sent = []

    def _complete(self, messages, use_tools=True):
        self.sent.append(messages)
        yield {"message": self.replies.pop(0) if self.replies else {"role": "assistant", "content": "ok"}}


@pytest.fixture
def store(tmp_path):
    return ChatStore(tmp_path / "chats", legacy=tmp_path / "sessions", uploads=tmp_path / "uploads")


def _png(path, payload=b"x" * 64):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + payload)
    return path


def test_save_and_load_roundtrip(store):
    s = Session()
    s.title = "My chat"
    s.messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello", "reasoning_content": "r"}]
    s.display = [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello", "events": [{"type": "final", "text": "hello"}]}]
    s.pa = {"reference": "x.png", "pending": ["L1"]}
    s.pending = {"call": {"id": "c1", "name": "write_workflow", "args": {"confirm": True}}, "remaining": []}
    s.gated_done = {"k": {"ok": True}}
    p = store.save(s)
    assert p == store.root / f"{s.id}.json" and p.is_file()
    rec = json.loads(p.read_text(encoding="utf-8"))
    assert rec["id"] == s.id and rec["title"] == "My chat" and rec["mode"] == "prompt_artist"
    assert rec["created"] <= rec["updated"] and len(rec["messages"]) == 2
    t = store.load(s.id)
    assert t.messages == s.messages and t.display == s.display and t.pa == s.pa
    assert t.pending == s.pending and t.gated_done == s.gated_done and t.title == "My chat"
    assert [c["id"] for c in store.list()] == [s.id]


def test_list_is_newest_first_and_searchable(store):
    a, b = Session(), Session()
    a.title, b.title = "Older about Pony", "Newer"
    b.display = [{"role": "user", "text": "silver hair octopus"}]
    store.save(a)
    time.sleep(0.01)
    store.save(b)
    assert [c["id"] for c in store.list()] == [b.id, a.id]
    assert [c["id"] for c in store.list("pony")] == [a.id]
    assert [c["id"] for c in store.list("OCTOPUS")] == [b.id]
    assert store.list("nothing like this") == []


def test_titles():
    assert make_title("Explain my Edit Flow workflow in simple words.") == "Explain my Edit Flow workflow in simple words."
    t = make_title("Prompt Artist: analyse this image and write the best prompt to recreate it.\nImage file: C:\\up\\20260101-120000_hero.png")
    assert t == "Prompt Artist: hero"
    t = make_title("Prompt Artist fix: here is the image I generated. What went wrong and how do I fix the prompt?\n"
                   "Note: hair should be silver\nImage file: C:\\a\\res.png")
    assert t == "Prompt Artist fix: res – hair should be silver"
    assert len(make_title("x" * 200)) <= 60
    assert make_title("") == "New chat"


def test_rename(store):
    s = store.create()
    store.rename(s, "  Workflow   H1 01 realistic ")
    t = store.load(s.id)
    assert t.title == "Workflow H1 01 realistic" and t.title_custom
    with pytest.raises(ValueError):
        store.rename(s, "   ")


def test_secure_delete_overwrites_then_removes(store, monkeypatch):
    s = Session()
    s.messages = [{"role": "user", "content": "SECRET-TEXT " * 50}]
    store.save(s)
    img = _png(store.files_dir(s.id) / "pic.png", b"SECRET-PIXELS" * 40)
    seen = []
    real_fsync = os.fsync

    def spy(fd):
        size = os.fstat(fd).st_size
        if size:
            pos = os.lseek(fd, 0, os.SEEK_CUR)
            os.lseek(fd, 0, os.SEEK_SET)
            seen.append(os.read(fd, size))
            os.lseek(fd, pos, os.SEEK_SET)
        return real_fsync(fd)
    monkeypatch.setattr(chats_mod.os, "fsync", spy)
    monkeypatch.setattr(chats_mod.os, "urandom", lambda n: b"\xa5" * n)
    res = store.delete(s.id)
    assert res["erased_files"] == 2
    assert len(seen) == 2 and all(set(b) == {0xA5} for b in seen)     # both files were overwritten before removal
    assert not store.path(s.id).exists() and not img.exists() and not store.files_dir(s.id).exists()
    assert list(store.root.iterdir()) == []                              # no renamed leftovers
    with pytest.raises(KeyError):
        store.delete(s.id)


def test_secure_wipe_missing_file(tmp_path):
    assert secure_wipe_file(tmp_path / "nope.bin") is False


def test_atomic_write_keeps_old_file_when_rename_fails(store, monkeypatch):
    s = Session()
    s.title = "first"
    p = store.save(s)
    before = p.read_text(encoding="utf-8")

    def boom(a, b):
        raise OSError("disk full")
    monkeypatch.setattr(chats_mod.os, "replace", boom)
    s.title = "second"
    with pytest.raises(OSError):
        store.save(s)
    assert p.read_text(encoding="utf-8") == before                      # old file untouched
    assert [f.name for f in store.root.iterdir()] == [p.name]          # temp file cleaned up


def test_atomic_write_uses_temp_then_rename(store, monkeypatch):
    calls = []
    real = os.replace

    def spy(a, b):
        calls.append((str(a), str(b)))
        assert json.loads(open(a, encoding="utf-8").read())["id"]      # temp file is complete before the rename
        return real(a, b)
    monkeypatch.setattr(chats_mod.os, "replace", spy)
    s = Session()
    store.save(s)
    assert len(calls) == 1 and calls[0][0].endswith(".tmp") and calls[0][1].endswith(f"{s.id}.json")


def test_restored_chat_feeds_previous_messages_to_agent(store):
    a = Scripted([{"role": "assistant", "content": "I made workflow H1_realistic.json for you."}])
    s = Session()
    list(a.chat(s, "remake my workflow H1 01 realistic"))
    store.save(s)

    fresh = ChatStore(store.root, legacy=store.legacy, uploads=store.uploads)   # app closed and reopened
    t = fresh.load(s.id)
    b = Scripted([{"role": "assistant", "content": "Thanks - the faces need more detail."}])
    evs = list(b.chat(t, "here's what the workflow you made produced"))
    assert evs[-1]["type"] == "final"
    sent = b.sent[0]
    assert sent[0]["role"] == "system"
    texts = [m.get("content") or "" for m in sent[1:]]
    assert texts[0].startswith("remake my workflow H1 01 realistic")
    assert "I made workflow H1_realistic.json for you." in texts
    assert texts[-1] == "here's what the workflow you made produced"


def test_restored_prompt_artist_state_keeps_reference(store, tmp_path):
    ref = _png(tmp_path / "uploads" / "20261027-120000_ref.png")
    s = Session()
    text, files = store.adopt_files(s, f"Prompt Artist: analyse this image\nImage file: {ref}")
    assert files[0]["kind"] == "image" and files[0]["url"] == f"/api/chats/{s.id}/files/{ref.name}"
    moved = store.files_dir(s.id) / ref.name
    assert moved.is_file() and not ref.exists() and str(moved) in text   # fresh upload moved into the chat folder
    s.pa = {"reference": str(moved), "answer": "### Prompt for Pony (`pony.safetensors`)"}
    store.save(s)
    t = store.load(s.id)
    assert t.pa["reference"] == str(moved) and store.file_path(s.id, ref.name) == moved
    with pytest.raises(KeyError):
        store.file_path(s.id, "../" + s.id + ".json")


def test_long_chat_trims_model_context_but_keeps_everything_on_disk(store):
    a = Scripted([{"role": "assistant", "content": "fine"}])
    a.llm["context_size"] = 16000
    s = Session()
    for i in range(40):
        s.messages += [{"role": "user", "content": f"question {i} " + "q" * 900},
                       {"role": "assistant", "content": f"answer {i} " + "a" * 900}]
    list(a.chat(s, "and now?"))
    store.save(s)
    sent = a.sent[0]
    assert len(sent) - 1 < len(s.messages)                   # older turns left out of the request
    assert sent[1]["role"] == "user" and sent[-1]["content"] == "and now?"
    assert "oldest turn(s) are left out" in sent[0]["content"]
    assert a.trimmed_turns > 0
    assert len(store.load(s.id).messages) == 82              # the saved chat keeps every message


def test_legacy_sessions_are_imported_once(store, tmp_path):
    up = _png(tmp_path / "uploads" / "20261027-222819_hero.png")
    store.legacy.mkdir(parents=True)
    old = {"id": "c910b53a00", "title": "Prompt Artist: analyse", "created": 1793140099.5, "messages": [
        {"role": "user", "content": f"Prompt Artist: analyse this image and write the best prompt to recreate it.\nImage file: {up}"
                                    "\n\n[Prompt Artist: the image was analysed by the vision model. Installed models:]\n- a"},
        {"role": "assistant", "content": "### Prompt for Illustrious (`wai.safetensors`)\nsilver hair"},
        {"role": "user", "content": "can you open that prompt in comfyui?\n\n[ComfyUI Expert note: playbook]"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "kb_list", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "name": "kb_list", "content": '{"ok": true}'},
        {"role": "assistant", "content": "Done."}]}
    src = store.legacy / "c910b53a00.json"
    src.write_text(json.dumps(old), encoding="utf-8")
    (store.legacy / "emptyone1.json").write_text(json.dumps({"id": "emptyone1", "messages": []}))
    before = src.read_bytes()
    assert store.import_legacy() == ["c910b53a00"]
    assert src.read_bytes() == before and up.exists()        # originals untouched (copied, not moved)
    s = store.load("c910b53a00")
    assert s.title == "Prompt Artist: hero" and s.messages[-1]["content"] == "Done."
    users = [d for d in s.display if d["role"] == "user"]
    assert users[1]["text"] == "can you open that prompt in comfyui?"
    assert users[0]["files"][0]["url"].endswith("/20261027-222819_hero.png")
    assert (store.files_dir("c910b53a00") / up.name).is_file()
    assert s.pa["reference"].endswith(up.name) and "silver hair" in s.pa["answer"]
    assert store.import_legacy() == []
    store.delete("c910b53a00")
    assert store.import_legacy() == []                         # a deleted chat does not come back


# ---------------------------------------------------------------- HTTP API (real server on a free port)
@pytest.fixture
def api(store):
    import uvicorn
    from comfy_expert.web.server import create_app
    agent = Scripted([{"role": "assistant", "content": "Use `--reserve-vram 2`."},
                      {"role": "assistant", "content": "Second answer."}])
    app = create_app(store=store, agent=agent)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}", agent
    server.should_exit = True
    th.join(10)


def _chat(base, sid, text):
    r = requests.post(base + "/api/chat", json={"session_id": sid, "message": text}, timeout=20)
    return [json.loads(l) for l in r.text.splitlines() if l.strip()]


def test_api_create_list_get_rename_delete(api, store):
    base, _ = api
    c = requests.post(base + "/api/chats", json={}, timeout=10).json()
    assert store.exists(c["id"])
    assert [x["id"] for x in requests.get(base + "/api/chats", timeout=10).json()["chats"]] == [c["id"]]
    r = requests.patch(base + f"/api/chats/{c['id']}", json={"title": "Renamed"}, timeout=10)
    assert r.json()["title"] == "Renamed" and store.load(c["id"]).title == "Renamed"
    assert requests.get(base + f"/api/chats/{c['id']}", timeout=10).json()["title"] == "Renamed"
    assert requests.patch(base + f"/api/chats/{c['id']}", json={"title": ""}, timeout=10).status_code == 400
    assert requests.delete(base + f"/api/chats/{c['id']}", timeout=10).json()["ok"] is True
    assert not store.exists(c["id"])
    assert requests.get(base + f"/api/chats/{c['id']}", timeout=10).status_code == 404
    assert requests.delete(base + f"/api/chats/{c['id']}", timeout=10).status_code == 404
    assert requests.get(base + "/api/chats/..%2Fsecret", timeout=10).status_code == 404


def test_api_chat_is_saved_and_reopened(api, store, tmp_path):
    base, agent = api
    evs = _chat(base, None, "how much vram should I reserve?")
    sid = evs[0]["id"]
    assert evs[0]["type"] == "session" and evs[-1]["type"] == "done"
    rec = store.load_record(sid)
    assert rec["title"] == "how much vram should I reserve?"
    assert [d["role"] for d in rec["display"]] == ["user", "assistant"]
    assert rec["display"][1]["text"].startswith("Use `--reserve-vram 2`.")
    got = requests.get(base + f"/api/chats/{sid}", timeout=10).json()
    assert got["display"][0]["text"] == "how much vram should I reserve?"
    assert any(e["type"] == "final" for e in got["display"][1]["events"])
    _chat(base, sid, "and then?")
    assert len(store.load(sid).messages) == 4
    assert agent.sent[1][1]["content"].startswith("how much vram")
    # an upload is moved into the chat folder and served back as a thumbnail
    up = requests.post(base + "/api/upload", files={"file": ("pic.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")}, timeout=10).json()
    _chat(base, sid, f"look at this workflow output\nWorkflow file: {up['path']}")
    files = store.load(sid).display[-2]["files"]
    assert files and files[0]["kind"] == "image"
    r = requests.get(base + files[0]["url"], timeout=10)
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    assert requests.delete(base + f"/api/chats/{sid}", timeout=10).json()["erased_files"] == 2
