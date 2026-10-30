"""The Stop button: cancels model generation (closes the llama-server stream), tools and the turn."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from comfy_expert.agent import Agent, Session
from comfy_expert.chats import ChatStore
from comfy_expert.tools import Turn


class SlowLlama(BaseHTTPRequestHandler):
    """Streams one token every 50 ms for ~30 s; records whether the client hung up."""
    state = {"tokens": 0, "disconnected": False}

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for i in range(600):
                chunk = {"choices": [{"delta": {"content": f"word{i} "}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                self.state["tokens"] += 1
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.state["disconnected"] = True


def _server():
    SlowLlama.state = {"tokens": 0, "disconnected": False}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SlowLlama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _agent(port):
    a = Agent()
    a.llm["base_url"] = f"http://127.0.0.1:{port}/v1"
    a.llm["stream"] = True
    a.model = lambda: "test-model"
    return a


def test_stop_cuts_generation_and_keeps_partial_answer():
    srv = _server()
    try:
        a = _agent(srv.server_address[1])
        s = Session()
        s.turn = Turn()
        evs = []
        t0 = time.time()
        th = threading.Thread(target=lambda: evs.extend(a.chat(s, "write a very long story")))
        th.start()
        time.sleep(0.6)
        s.turn.stop.set()
        th.join(5)
        assert not th.is_alive() and time.time() - t0 < 4
        assert evs[-1]["type"] == "stopped" and evs[-1]["text"].startswith("word0")
        assert s.messages[-1]["role"] == "assistant" and "[stopped by the user]" in s.messages[-1]["content"]
        time.sleep(0.3)
        assert SlowLlama.state["disconnected"] and SlowLlama.state["tokens"] < 100
    finally:
        srv.shutdown()


def test_stop_does_not_wait_for_a_slow_tool(monkeypatch):
    from comfy_expert import agent as agent_mod
    monkeypatch.setattr(agent_mod, "run_tool", lambda n, a: (time.sleep(20), {"ok": True})[1])
    a = Agent()
    s = Session()
    s.turn = Turn()
    s.messages = [{"role": "user", "content": "x"},
                  {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
                   "function": {"name": "kb_list", "arguments": "{}"}}]}]
    threading.Timer(0.4, s.turn.stop.set).start()
    t0 = time.time()
    with __import__("pytest").raises(agent_mod.Stopped):
        a._tool(s, "kb_list", {})
    assert time.time() - t0 < 2
    a._finish_stopped(s, "")
    assert s.messages[-2]["role"] == "tool" and s.messages[-2]["tool_call_id"] == "c1"


def test_api_stop_endpoint(tmp_path):
    from fastapi.testclient import TestClient
    from comfy_expert.web import server
    srv = _server()
    try:
        a = _agent(srv.server_address[1])
        c = TestClient(server.create_app(store=ChatStore(tmp_path / "chats", legacy=tmp_path / "sessions", uploads=tmp_path / "uploads"), agent=a))
        out = {}

        def talk():
            r = c.post("/api/chat", json={"message": "long story please"})
            out["lines"] = [json.loads(l) for l in r.text.splitlines() if l.strip()]
        th = threading.Thread(target=talk)
        th.start()
        time.sleep(0.8)
        r = c.get("/api/chats").json()["chats"]
        sid = r[0]["id"]
        j = c.post("/api/stop", json={"session_id": sid}).json()
        th.join(5)
        assert j["stopped"] and j["ended"]
        types = [e["type"] for e in out["lines"]]
        assert "stopped" in types and types[-1] == "done"
        saved = c.get("/api/chats/" + sid).json()
        assert any(e.get("type") == "stopped" for d in saved["display"] for e in d.get("events", []))
        assert c.post("/api/stop", json={"session_id": sid}).json()["stopped"] is False
    finally:
        srv.shutdown()


def test_stop_cancels_comfy_jobs_it_queued(tmp_path):
    """Stop removes this turn's pending ComfyUI prompts and interrupts the one that is running."""
    from fastapi.testclient import TestClient
    from comfy_expert.web import server
    seen = []

    class FakeComfy(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            self._send({"queue_running": [[1, "p1", {}]], "queue_pending": [[2, "p2", {}], [3, "other", {}]]})

        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")))
            self._send({})
    cs = ThreadingHTTPServer(("127.0.0.1", 0), FakeComfy)
    threading.Thread(target=cs.serve_forever, daemon=True).start()
    srv = _server()
    try:
        a = _agent(srv.server_address[1])
        app = server.create_app(store=ChatStore(tmp_path / "chats", legacy=tmp_path / "sessions", uploads=tmp_path / "uploads"), agent=a)
        c = TestClient(app)
        th = threading.Thread(target=lambda: c.post("/api/chat", json={"message": "go"}))
        th.start()
        time.sleep(0.6)
        sid = c.get("/api/chats").json()["chats"][0]["id"]
        # pretend this turn queued two ComfyUI jobs
        import gc
        sess = next(o for o in gc.get_objects() if isinstance(o, Session) and o.id == sid)
        sess.turn.comfy_prompts += ["p1", "p2"]
        sess.turn.comfy_url = f"http://127.0.0.1:{cs.server_address[1]}"
        j = c.post("/api/stop", json={"session_id": sid}).json()
        th.join(5)
        assert j["comfy"]["removed_from_queue"] == ["p2"] and j["comfy"]["interrupted"] == ["p1"]
        assert ("/queue", {"delete": ["p2"]}) in seen and seen[-1][0] == "/interrupt"
    finally:
        srv.shutdown()
        cs.shutdown()
