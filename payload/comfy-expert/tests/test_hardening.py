"""Resilience: damaged chat / cache / lessons files, odd llama-server and ComfyUI answers, Stop only cancelling
this turn's ComfyUI jobs (also when Stop races the queueing), and verified, resumable model downloads."""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from comfy_expert.agent import Agent, LLMError
from comfy_expert.chats import ChatStore, DamagedChat
from comfy_expert.config import load_config
from comfy_expert.tools import TURN, ToolError, Turn, comfy, downloads, lessons, run_tool, web


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class JSONHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, status=200, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


# ------------------------------------------------------------------ chats
def _store(tmp_path):
    return ChatStore(tmp_path / "chats", legacy=tmp_path / "sessions", uploads=tmp_path / "uploads")


@pytest.mark.parametrize("junk", [b'{"id": "abc", "messages": [', b"\xff\xfe\x00", b"[1, 2]", b'"text"'])
def test_damaged_chat_file_is_reported_and_kept(tmp_path, junk):
    from fastapi.testclient import TestClient
    from comfy_expert.web import server
    store = _store(tmp_path)
    good = store.create("fine")
    store.save(good)
    bad = store.path("abcdef123456")
    bad.write_bytes(junk)
    with pytest.raises(DamagedChat):
        store.load("abcdef123456")
    assert [c["id"] for c in store.list()] == [good.id]
    c = TestClient(server.create_app(store=store, agent=Agent()))
    r = c.get("/api/chats/abcdef123456")
    assert r.status_code == 422 and "damaged" in r.json()["detail"]
    assert c.post("/api/chat", json={"message": "hi", "session_id": "abcdef123456"}).status_code == 422
    assert bad.read_bytes() == junk                      # never deleted or overwritten
    assert c.get("/api/chats/" + good.id).status_code == 200


def test_odd_chat_records_load(tmp_path):
    store = _store(tmp_path)
    store.path("abcdef123456").write_text(json.dumps({"id": "abcdef123456", "created": "yesterday", "messages": [1, {"role": "user", "content": "x"}],
                                                      "display": "nope", "state": [], "title": 5}))
    s = store.load("abcdef123456")
    assert s.messages == [{"role": "user", "content": "x"}] and s.display == [] and s.title == ""
    store.path("bcdef1234567").write_text(json.dumps({"id": "bcdef1234567", "display": [5, {"role": "user", "files": [3]}], "updated": "x"}))
    assert len(store.list()) == 2


def test_bad_request_bodies(tmp_path):
    from fastapi.testclient import TestClient
    from comfy_expert.web import server
    c = TestClient(server.create_app(store=_store(tmp_path), agent=Agent()))
    assert c.post("/api/chat", content=b"not json", headers={"content-type": "application/json"}).status_code == 400
    assert c.post("/api/chat", json=[1, 2]).status_code == 400
    assert c.post("/api/chat", json={"message": 5}).status_code == 400
    assert c.post("/api/confirm", json="x").status_code == 400
    assert c.post("/api/stop", json={"session_id": ["x"]}).json()["stopped"] is False
    cid = c.post("/api/chats", json={"title": ["x"]}).json()["id"]
    assert c.patch("/api/chats/" + cid, json={"title": 5}).status_code == 400


def test_chat_file_names_cannot_leave_the_chat_folder(tmp_path):
    store = _store(tmp_path)
    for name in ("C:secret.txt", "..", "a/b", "x\0y"):
        with pytest.raises(KeyError):
            store.file_path("abcdef123456", name)


# ------------------------------------------------------------------ llama-server answers
def test_odd_tool_call_shapes():
    P = Agent.parse_tool_calls
    assert P({"content": None, "tool_calls": "x"}) == ("", [])
    _, calls = P({"content": "", "tool_calls": [5, {"function": "x"}, {"function": {"name": "kb_list", "arguments": "[1]"}}]})
    assert [c["name"] for c in calls] == ["", "kb_list"] and calls[1]["args"] == {"__invalid_json__": "[1]"}
    _, calls = P({"content": '<tool_call>["a"]</tool_call><tool_call>{"name": "kb_list", "arguments": [1]}</tool_call>'})
    assert calls and calls[0]["name"] == "kb_list" and calls[0]["args"] == {}
    assert P("not a dict") == ("", [])
    assert run_tool("kb_list", [1, 2])["ok"] is False


@pytest.mark.parametrize("body", [b"<html>", b"{}", b'{"choices": []}', b'{"choices": [{"message": "x"}]}'])
def test_unexpected_non_stream_answer_is_an_llm_error(body):
    class H(JSONHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send(None, raw=body)
    srv, url = _serve(H)
    try:
        a = Agent()
        a.llm["base_url"], a.llm["stream"] = url + "/v1", False
        a.model = lambda: "m"
        with pytest.raises(LLMError):
            list(a._complete_once([{"role": "user", "content": "x"}], use_tools=False))
    finally:
        srv.shutdown()


def test_odd_stream_chunks_are_skipped():
    chunks = [5, {"choices": "x"}, {"choices": [3, {"delta": "x"}, {"delta": {"content": 7, "tool_calls": [1, {"index": "a", "function": {"name": "kb_list"}}]}}]},
              {"choices": [{"delta": {"content": "hello"}}]}]

    class H(JSONHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for c in chunks:
                self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
    srv, url = _serve(H)
    try:
        a = Agent()
        a.llm["base_url"], a.llm["stream"] = url + "/v1", True
        a.model = lambda: "m"
        msg = list(a._complete_once([{"role": "user", "content": "x"}], use_tools=False))[-1]["message"]
        assert msg["content"] == "hello" and msg["tool_calls"][0]["function"]["name"] == "kb_list"
    finally:
        srv.shutdown()


# ------------------------------------------------------------------ ComfyUI
class FakeComfy(JSONHandler):
    seen: list = []
    queue: dict = {}
    on_prompt = None
    history: list = []

    def do_GET(self):
        if self.path == "/system_stats":
            return self.send({"system": {}, "devices": "x"})
        if self.path == "/object_info":
            return self.send(["not", "a", "dict"])
        if self.path == "/queue":
            return self.send(FakeComfy.queue)
        if self.path.startswith("/history/"):
            h = FakeComfy.history.pop(0) if FakeComfy.history else {}
            return self.send(None, raw=h if isinstance(h, bytes) else json.dumps(h).encode())
        self.send({}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        FakeComfy.seen.append((self.path, body))
        if self.path == "/prompt":
            if FakeComfy.on_prompt:
                FakeComfy.on_prompt()
            return self.send({"prompt_id": "mine", "number": 1})
        self.send({})


@pytest.fixture
def fake_comfy(monkeypatch):
    FakeComfy.seen, FakeComfy.history, FakeComfy.on_prompt = [], [], None
    FakeComfy.queue = {"queue_running": [[0, "theirs-running", {}]], "queue_pending": [[1, "mine", {}], [2, "theirs", {}]]}
    srv, url = _serve(FakeComfy)
    monkeypatch.setitem(load_config()["comfyui"], "url", url)
    yield url
    srv.shutdown()


def test_cancel_only_touches_our_jobs(fake_comfy):
    out = comfy.cancel_prompts(fake_comfy, ["mine", "gone", 5])
    assert out["removed_from_queue"] == ["mine"] and "interrupted" not in out
    assert FakeComfy.seen == [("/queue", {"delete": ["mine"]})]
    FakeComfy.queue = {"queue_running": "x", "queue_pending": [5, [1], [2, None], [3, "mine"]]}
    FakeComfy.seen = []
    assert comfy.cancel_prompts(fake_comfy, ["mine"])["removed_from_queue"] == ["mine"]
    FakeComfy.queue = ["odd"]
    assert "error" not in comfy.cancel_prompts(fake_comfy, ["mine"])


def test_non_dict_object_info_falls_back_to_bundled(fake_comfy):
    data, source = comfy.get_object_info(force=True)
    assert isinstance(data, dict) and data and source.startswith("bundled")
    assert comfy.comfy_status()["running"] is True


def test_stop_pressed_while_the_job_is_being_queued_cancels_it(fake_comfy):
    turn = Turn()
    FakeComfy.on_prompt = turn.stop.set           # Stop arrives while POST /prompt is in flight
    tok = TURN.set(turn)
    try:
        r = run_tool("comfy_queue_test", {"source": "sdxl_txt2img", "confirm": True})
    finally:
        TURN.reset(tok)
    assert r["status"] == "stopped by the user", r
    assert ("/queue", {"delete": ["mine"]}) in FakeComfy.seen
    assert not any(p == "/interrupt" for p, _ in FakeComfy.seen)       # someone else's running job is left alone
    assert turn.comfy_prompts == ["mine"]


def test_history_poll_survives_odd_answers(fake_comfy):
    FakeComfy.history = [b"<html>busy</html>", ["x"], {"mine": "x"},
                         {"mine": {"status": {"status_str": "success", "completed": True, "messages": [5, ["execution_error", {"m": 1}]]},
                                   "outputs": {"9": {"images": [{"filename": "a.png", "subfolder": ""}, 3]}, "8": "x"}}}]
    r = run_tool("comfy_queue_test", {"source": "sdxl_txt2img", "confirm": True, "wait_seconds": 30})
    assert r["status"] == "success" and r["outputs"] == ["a.png"] and r["errors"] == [{"m": 1}], r


# ------------------------------------------------------------------ caches / lessons
def test_corrupt_node_map_cache_is_refetched(tmp_path, monkeypatch):
    class H(JSONHandler):
        def do_GET(self):
            self.send({"https://github.com/x/pack": [["FaceDetailer"], {"title_aux": "Pack"}]})
    srv, url = _serve(H)
    try:
        monkeypatch.setattr(web, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(web, "NODE_MAP_URL", url + "/map.json")
        (tmp_path / "extension-node-map.json").write_text('{"cut off')
        assert "https://github.com/x/pack" in web._node_map()
        assert json.loads((tmp_path / "extension-node-map.json").read_text())
    finally:
        srv.shutdown()


def test_damaged_lessons_file_is_kept_aside(tmp_path, monkeypatch):
    p = tmp_path / "lessons.json"
    monkeypatch.setattr(lessons, "path", lambda: p)
    p.write_text('{"lessons": [{"symptom": "a"')
    assert lessons.load() == []
    assert [x.name for x in tmp_path.iterdir() if ".corrupt-" in x.name]
    p.write_text(json.dumps({"lessons": [1, {"symptom": "s"}]}))
    assert lessons.load() == [{"symptom": "s"}]


# ------------------------------------------------------------------ downloads
DATA = bytes(range(256)) * 1200
SHA = hashlib.sha256(DATA).hexdigest()


class FileHandler(BaseHTTPRequestHandler):
    mode = "normal"
    hits: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        FileHandler.hits.append(self.headers.get("Range"))
        m = FileHandler.mode
        if m == "404":
            return self.send_error(404)
        body = DATA
        if m == "corrupt" or (m == "corrupt-once" and len([h for h in FileHandler.hits if h != "bytes=0-0"]) == 1):
            body = b"\x01" + DATA[1:]
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(body):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(body)}")
                self.end_headers()
                return
            s2 = max(0, start - 10) if m == "bad-range" and start else start
            self.send_response(206)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Range", f"bytes {s2}-{len(body) - 1}/{len(body)}")
            self.send_header("Content-Length", str(len(body) - s2))
            self.end_headers()
            self.wfile.write(body[s2:])
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def files(offline_cfg):
    FileHandler.mode, FileHandler.hits = "normal", []
    srv, url = _serve(FileHandler)
    yield url + "/m.safetensors", offline_cfg["models"] / "loras"
    srv.shutdown()


def _dl(url, sha=SHA):
    return downloads.download_file(url, "loras", sha256=sha, confirm=True)


def test_download_normal_and_existing_file_is_verified(files):
    url, d = files
    assert _dl(url)["sha256_checked"]
    assert (d / "m.safetensors").read_bytes() == DATA
    assert downloads.download_file(url, "loras", sha256=SHA)["skipped"]
    (d / "m.safetensors").write_bytes(b"\x01" + DATA[1:])       # same size, other bytes: not "already downloaded"
    with pytest.raises(ToolError):
        _dl(url)


def test_download_resume_and_bad_partials(files):
    url, d = files
    part = d / "m.safetensors.part"
    for mode, partial in (("normal", DATA[:5000]), ("normal", DATA + b"junk"), ("normal", b"\x01" * len(DATA)),
                          ("bad-range", DATA[:5000])):
        FileHandler.mode = mode
        part.write_bytes(partial)
        r = _dl(url)
        assert r.get("downloaded"), (mode, r)
        assert (d / "m.safetensors").read_bytes() == DATA and not part.exists()
        (d / "m.safetensors").unlink()


def test_download_sha_mismatch_retried_once_then_refused(files):
    url, d = files
    FileHandler.mode = "corrupt-once"
    assert _dl(url)["downloaded"]
    (d / "m.safetensors").unlink()
    FileHandler.mode = "corrupt"
    with pytest.raises(ToolError, match="twice"):
        _dl(url)
    assert not list(d.glob("m.safetensors*"))


def test_download_fails_fast_and_checks_sha_format(files):
    url, _ = files
    FileHandler.mode = "404"
    with pytest.raises(ToolError):
        _dl(url)
    assert len(FileHandler.hits) == 1
    FileHandler.mode = "normal"
    with pytest.raises(ToolError, match="64"):
        _dl(url, sha="1234")
    assert _dl(url, sha="sha256:" + SHA.upper())["downloaded"]

