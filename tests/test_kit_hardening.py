"""Setup-kit resilience tests: corrupt caches, stale / reused PIDs, malformed model choices, bad downloads (local
HTTP server), the HomeAI link and its undo, ComfyUI install safety. Standard library only:

    python -m unittest discover -s tests -v
"""
import hashlib
import http.server
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit"))

from cesetup import comfyui, control, hfcore as H, hfsearch as S, homeai_link as HL, llamacpp, main as M, models, uninstall  # noqa: E402

H.RETRY_SLEEP = 0
quiet = lambda: redirect_stdout(io.StringIO())  # noqa: E731


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


# ------------------------------------------------------------------------------------------------ 1. cache
class CacheTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.hf = S.hf_client(self.d)
        self.calls = 0

        def fake_open(url, headers=None, timeout=60):
            self.calls += 1
            return FakeResp(json.dumps([{"id": "a/b"}]).encode())
        self.hf.open = fake_open
        self.url = self.hf.API + "/api/models/x"

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_corrupt_cache_is_a_miss_and_is_replaced(self):
        for junk in (b'[{"id": "a/', b"\xff\xfe\x00garbage", b""):
            cp = self.hf._cache_path(self.url)
            with open(cp, "wb") as f:
                f.write(junk)
            self.assertEqual(self.hf.get_json("/api/models/x"), [{"id": "a/b"}])
            with open(cp, encoding="utf-8") as f:
                self.assertEqual(json.load(f), [{"id": "a/b"}])
        self.assertEqual(self.calls, 3)
        self.assertEqual(self.hf.get_json("/api/models/x"), [{"id": "a/b"}])   # now a good cache hit
        self.assertEqual(self.calls, 3)

    def test_store_is_atomic_and_leaves_no_temp_files(self):
        cp = self.hf._cache_path(self.url)
        H.HF._store(cp, {"ok": 1})
        H.HF._store(cp, {"bad": object()})          # cannot be serialised: old cache must survive intact
        with open(cp, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"ok": 1})
        self.assertEqual(os.listdir(self.d), [os.path.basename(cp)])

    def test_non_json_network_answer_is_an_error_not_a_crash(self):
        self.hf.open = lambda *a, **k: FakeResp(b"<html>proxy login</html>")
        with mock_sleep():
            self.assertIsNone(self.hf.get_json("/api/models/y"))
        self.assertTrue(any("not valid JSON" in e for e in self.hf.errors))
        self.assertEqual(self.hf.tree("a/b"), [])
        self.assertEqual(self.hf.search("x"), [])

    def test_wrong_shape_answers(self):
        self.hf.open = lambda *a, **k: FakeResp(b'{"error": "nope"}')
        self.assertEqual(self.hf.tree("a/b"), [])
        self.assertEqual(S._search(self.hf, "t", None, "downloads", 5), [])
        self.hf.open = lambda *a, **k: FakeResp(b'[1, "x", {"type": "file"}, {"type": "file", "path": "m-Q4_K_M.gguf", '
                                                b'"size": 10, "lfs": "weird"}]')
        quants, _ = H.pick_files(self.hf.tree("c/d"))
        self.assertEqual(list(quants), ["Q4_K_M"])
        c = H.Cand({"id": "a/b-8B", "cardData": ["not", "a", "dict"], "gguf": "x", "downloads": "many"})
        self.assertEqual((c.base_models, c.downloads, c.api_arch), ([], 0, None))


class mock_sleep:
    def __enter__(self):
        self.orig = time.sleep
        time.sleep = lambda s: None

    def __exit__(self, *a):
        time.sleep = self.orig


# ------------------------------------------------------------------------------------------------ 2. pid files
@unittest.skipIf(os.name == "nt" or not os.path.isdir("/proc"), "Linux /proc checks")
class PidTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
        shutil.rmtree(self.root, ignore_errors=True)

    def dummy(self, tag, new_session=True):
        cmd = [sys.executable, "-c", "import time; time.sleep(120)", tag]
        p = subprocess.Popen(cmd, start_new_session=new_session)
        self.procs.append(p)
        time.sleep(0.2)
        return p, cmd

    def alive(self, p, wait=3.0):
        end = time.time() + wait
        while time.time() < end:
            if p.poll() is not None:
                return False
            time.sleep(0.05)
        return p.poll() is None

    def pf(self, name="llama"):
        return control._pidfile(self.root, name)

    def test_own_process_is_stopped(self):
        cmd = [sys.executable, "-c", "import time; time.sleep(120)", "ce-own"]
        p = control._spawn(self.root, "llama", cmd, self.root)
        self.procs.append(p)
        time.sleep(0.2)
        rec = control.read_pidfile(self.pf())
        self.assertEqual((rec["pid"], rec["cmd"]), (p.pid, cmd))
        self.assertIsNotNone(rec["start"])
        with quiet():
            self.assertTrue(control._kill(self.root, "llama", cmd))
        p.wait(3)
        self.assertEqual(p.returncode, -signal.SIGTERM)
        self.assertFalse(os.path.exists(self.pf()))

    def test_stale_pid_pointing_at_unrelated_process_is_not_killed(self):
        other, _ = self.dummy("unrelated-app")
        with open(self.pf(), "w") as f:
            json.dump({"pid": other.pid, "start": control._proc_start(other.pid),
                       "cmd": ["/opt/ce/engine/llama.cpp/llama-server", "--port", "8081"]}, f)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(control._kill(self.root, "llama"))
        self.assertTrue(self.alive(other, 0.5))
        self.assertFalse(os.path.exists(self.pf()))           # stale pid file cleaned up
        self.assertIn("nothing stopped", out.getvalue())

    def test_reused_pid_with_same_command_but_other_start_time_is_not_killed(self):
        other, cmd = self.dummy("looks-like-ours")
        with open(self.pf(), "w") as f:
            json.dump({"pid": other.pid, "start": control._proc_start(other.pid) - 1, "cmd": cmd}, f)
        with quiet():
            self.assertFalse(control._kill(self.root, "llama", cmd))
        self.assertTrue(self.alive(other, 0.5))

    def test_old_style_bare_number_pid_file(self):
        other, _ = self.dummy("unrelated")
        with open(self.pf(), "w") as f:
            f.write(str(other.pid))
        with quiet():
            self.assertFalse(control._kill(self.root, "llama", ["/x/llama-server", "--port", "8081"]))
            self.assertFalse(control._kill(self.root, "llama"))     # (pid file already gone)
        self.assertTrue(self.alive(other, 0.5))
        ours, cmd = self.dummy("legacy-ours")
        with open(self.pf(), "w") as f:
            f.write(str(ours.pid))
        with quiet():
            self.assertTrue(control._kill(self.root, "llama", cmd))
        ours.wait(3)
        self.assertIsNotNone(ours.poll())

    def test_dead_pid_and_garbage_pid_files(self):
        p, cmd = self.dummy("short")
        p.kill(); p.wait()
        for content in (json.dumps({"pid": p.pid, "cmd": cmd}), "not a pid", "", "-5", '{"pid": "x"}', "[1,2]"):
            with open(self.pf(), "w") as f:
                f.write(content)
            with quiet():
                self.assertFalse(control._kill(self.root, "llama", cmd))
            self.assertFalse(os.path.exists(self.pf()))
        with quiet():
            self.assertFalse(control._kill(self.root, "llama", cmd))   # no pid file at all

    def test_killpg_only_for_our_own_group(self):
        # not a group leader (shares the test's group): must get a plain kill, never killpg on our own group
        p, cmd = self.dummy("no-session", new_session=False)
        with open(self.pf(), "w") as f:
            json.dump({"pid": p.pid, "start": control._proc_start(p.pid), "cmd": cmd}, f)
        with quiet():
            self.assertTrue(control._kill(self.root, "llama"))
        p.wait(3)
        self.assertEqual(p.returncode, -signal.SIGTERM)


# ------------------------------------------------------------------------------------------------ 5. downloads
DATA = os.urandom(300_000)
SHA = hashlib.sha256(DATA).hexdigest()


class Handler(http.server.BaseHTTPRequestHandler):
    mode = "normal"
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.hits.append((self.path, self.headers.get("Range")))
        mode = Handler.mode
        if mode == "404":
            self.send_error(404); return
        body, start = DATA, 0
        if mode == "corrupt" or (mode == "corrupt-once" and len(Handler.hits) == 1):
            body = bytes([DATA[0] ^ 1]) + DATA[1:]
        if mode == "oversize":
            body = DATA + b"extra"
        rng = self.headers.get("Range")
        if rng and mode not in ("ignore-range",):
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(body):
                self.send_response(416); self.send_header("Content-Range", "bytes */%d" % len(body))
                self.end_headers(); return
            if mode == "bad-range":
                start2 = max(0, start - 10)
            else:
                start2 = start
            self.send_response(206)
            if mode == "cut-always":
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, len(body) - 1, len(body)))
                self.send_header("Content-Length", str(len(body) - start))
                self.end_headers()
                self.wfile.write(body[start:start + 1000]); return
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start2, len(body) - 1, len(body)))
            self.send_header("Content-Length", str(len(body) - start2))
            self.end_headers()
            self.wfile.write(body[start2:]); return
        self.send_response(200)
        if mode != "no-length":
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if mode in ("cut", "cut-always"):
            self.wfile.write(body[:1000]); return
        self.wfile.write(body)


class FakeHF:
    def __init__(self, port):
        self.port = port

    def file_url(self, repo, path):
        return "http://127.0.0.1:%d/%s" % (self.port, path)

    def open(self, url, headers=None, timeout=60):
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout)


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.hf = FakeHF(cls.srv.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.d = tempfile.mkdtemp()
        Handler.hits = []
        Handler.mode = "normal"
        self.final = os.path.join(self.d, "m.gguf")
        self.part = self.final + ".part"

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def dl(self, size=len(DATA), sha=SHA):
        out = io.StringIO()
        with redirect_stdout(out):
            ok, path = H.download_file(self.hf, "r/x", "m.gguf", self.d, size, sha)
        self.log = out.getvalue()
        return ok, path

    def assert_good(self, ok, path):
        self.assertTrue(ok, self.log)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), DATA)
        self.assertFalse(os.path.exists(self.part))

    def assert_failed(self, ok, path):
        self.assertFalse(ok, self.log)
        self.assertIsNone(path)
        self.assertFalse(os.path.exists(self.final))

    def write_part(self, b):
        with open(self.part, "wb") as f:
            f.write(b)

    def test_normal(self):
        self.assert_good(*self.dl())

    def test_resume_from_good_partial(self):
        self.write_part(DATA[:1234])
        self.assert_good(*self.dl())
        self.assertEqual(Handler.hits[0][1], "bytes=1234-")

    def test_partial_larger_than_expected_is_deleted_and_refetched(self):
        self.write_part(DATA + b"junk")
        self.assert_good(*self.dl())
        self.assertIsNone(Handler.hits[0][1])
        self.assertFalse([f for f in os.listdir(self.d) if "oversize" in f])

    def test_server_ignoring_range_restarts_cleanly(self):
        Handler.mode = "ignore-range"
        self.write_part(DATA[:5000])
        self.assert_good(*self.dl())
        self.assertIn("ignored resume", self.log)

    def test_server_resuming_at_wrong_offset(self):
        Handler.mode = "bad-range"
        self.write_part(DATA[:5000])
        self.assert_good(*self.dl())

    def test_full_size_partial_with_bad_bytes_is_retried_once(self):
        self.write_part(b"\0" * len(DATA))            # right size, wrong content (bad resume state)
        self.assert_good(*self.dl())
        self.assertIn("trying once more", self.log)

    def test_sha_mismatch_once_then_good(self):
        Handler.mode = "corrupt-once"
        self.assert_good(*self.dl())
        self.assertEqual(len(Handler.hits), 2)

    def test_sha_mismatch_twice_fails_and_cleans_up(self):
        Handler.mode = "corrupt"
        self.assert_failed(*self.dl())
        self.assertFalse(os.listdir(self.d), "bad partial must be deleted")
        self.assertIn("FAILED again", self.log)

    def test_server_sends_too_much(self):
        Handler.mode = "oversize"
        self.assert_failed(*self.dl())
        self.assertIn("server says this file is", self.log)

    def test_listing_size_differs_from_file(self):
        self.assert_failed(*self.dl(size=len(DATA) - 1, sha=None))

    def test_missing_sha_verifies_size_and_warns(self):
        ok, path = self.dl(sha=None)
        self.assert_good(ok, path)
        self.assertIn("no SHA-256", self.log)
        self.assertIn("size verified", self.log)

    def test_unknown_size_learned_from_server(self):
        self.assert_good(*self.dl(size=None))

    def test_nothing_known_is_refused(self):
        Handler.mode = "no-length"
        self.assert_failed(*self.dl(size=None, sha=None))
        self.assertIn("cannot be verified", self.log)

    def test_invalid_sha_value_is_treated_as_missing(self):
        ok, _ = self.dl(sha="1234abcd")               # git sha1-ish / junk: not a SHA-256
        self.assertTrue(ok, self.log)
        self.assertIn("not a SHA-256", self.log)

    def test_connection_cut_is_resumed(self):
        Handler.mode = "cut"                          # first answer cut short, the resumed (Range) answer is fine
        self.assert_good(*self.dl())
        self.assertEqual(Handler.hits[1][1], "bytes=1000-")

    def test_connection_keeps_dropping_keeps_partial_for_later_resume(self):
        Handler.mode = "cut-always"
        self.assert_failed(*self.dl())
        self.assertIn("incomplete", self.log)
        self.assertEqual(os.path.getsize(self.part), 6000)
        Handler.mode = "normal"
        Handler.hits = []
        self.assert_good(*self.dl())
        self.assertEqual(Handler.hits[0][1], "bytes=6000-")

    def test_http_404_fails_fast(self):
        Handler.mode = "404"
        self.assert_failed(*self.dl())
        self.assertEqual(len(Handler.hits), 1)

    def test_existing_file_checks(self):
        with open(self.final, "wb") as f:
            f.write(DATA)
        self.assertTrue(self.dl()[0])
        self.assertFalse(self.dl(size=len(DATA) + 1)[0])
        self.assertFalse(self.dl(size=None, sha=None)[0])
        self.assertEqual(Handler.hits, [])

    def test_llamacpp_download_retries_bad_sha_and_rejects(self):
        orig = llamacpp._open
        llamacpp._open = lambda url, timeout=60, headers=None: self.hf.open(url, headers, timeout)
        try:
            dest = os.path.join(self.d, "llama.tgz")
            Handler.mode = "corrupt"
            with quiet(), self.assertRaises(RuntimeError):
                llamacpp.download(self.hf.file_url("", "llama.tgz"), dest, len(DATA), SHA)
            self.assertFalse(os.path.exists(dest))
            Handler.mode = "corrupt-once"
            Handler.hits = []
            with quiet():
                llamacpp.download(self.hf.file_url("", "llama.tgz"), dest, len(DATA), SHA)
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), DATA)
        finally:
            llamacpp._open = orig


# ------------------------------------------------------------------------------------------------ 6. stop()
@unittest.skipIf(os.name == "nt" or not os.path.isdir("/proc"), "Linux /proc checks")
class StopTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        with open(os.path.join(self.root, "install.json"), "w") as f:
            json.dump({"ui_port": 7999, "brain": {"model": "/m/x.gguf", "port": 8099}}, f)
        self.p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "unrelated"], start_new_session=True)
        time.sleep(0.2)

    def tearDown(self):
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_stop_with_stale_pid_files_stops_nothing(self):
        for name in ("app", "llama"):
            with open(control._pidfile(self.root, name), "w") as f:
                f.write(str(self.p.pid))                  # old-style bare pid, now some other program
        out = io.StringIO()
        with redirect_stdout(out):
            control.stop(self.root)
        time.sleep(0.3)
        self.assertIsNone(self.p.poll(), "an unrelated process was killed")
        self.assertEqual(out.getvalue().count("nothing stopped"), 2)
        self.assertFalse(os.listdir(os.path.join(self.root, "run")))

    def test_damaged_install_json(self):
        with open(os.path.join(self.root, "install.json"), "w") as f:
            f.write("[1, 2")
        self.assertEqual(control.state(self.root), {})
        with open(os.path.join(self.root, "install.json"), "w") as f:
            f.write("[1, 2]")
        self.assertEqual(control.state(self.root), {})
        with quiet():
            control.stop(self.root)
            self.assertFalse(control.start_brain(self.root, wait=1))
        self.assertEqual(uninstall.main(root=self.root, ask=type("A", (), {"ask": lambda *a: ""})()), 2)


# ------------------------------------------------------------------------------------------------ 7. choices
class ChoiceTests(unittest.TestCase):
    def test_malformed_choices_are_refused_before_any_download(self):
        orig = H.download_file
        H.download_file = lambda *a, **k: self.fail("must not download")
        try:
            for bad in (None, {}, {"repo": "a/b"}, {"repo": "a/b", "files": []}, {"repo": "a/b", "files": [{}]},
                        {"repo": "a/b", "files": ["x.gguf"]}, {"repo": None, "files": [{"path": "x.gguf"}]}):
                with quiet():
                    self.assertEqual(models.download(None, "/tmp/nowhere", bad), (False, None, None), repr(bad))
        finally:
            H.download_file = orig


class AnswersTests(unittest.TestCase):
    def test_bad_answers_file_is_a_clear_error(self):
        d = tempfile.mkdtemp()
        try:
            for content in ("{not json", "[1, 2]", ""):
                p = os.path.join(d, "a.json")
                with open(p, "w") as f:
                    f.write(content)
                with quiet():
                    self.assertEqual(M.main(["--answers", p]), 2)
            with quiet():
                self.assertEqual(M.main(["--answers", os.path.join(d, "missing.json")]), 2)
        finally:
            shutil.rmtree(d)


# ------------------------------------------------------------------------------------------------ 8. HomeAI link
INI = (b"; HomeAI models\r\n[general]\r\nmodel = /h/a.gguf\r\nctx-size = 8192\r\n\r\n"
       b"; the coder mode\r\n[coder]\r\nmodel = /h/b.gguf\r\n")


class HomeAILinkTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "engine"))
        os.makedirs(os.path.join(self.d, "homeai", "data"))
        self.ini = os.path.join(self.d, "engine", "models.ini")
        with open(self.ini, "wb") as f:
            f.write(INI)
        with open(os.path.join(self.d, "install.json"), "w") as f:
            json.dump({"models": {"general": {"model": "/h/a.gguf"}, "coder": {"model": "/h/b.gguf"}}}, f)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def read(self):
        with open(self.ini, "rb") as f:
            return f.read()

    def test_add_and_undo_keep_everything_else_byte_for_byte(self):
        h = HL.inspect(self.d)
        self.assertEqual(h["models"], ["coder", "general"])
        made = []
        HL.add_section(h, "ComfyUI-Expert-x-Q4", "/c/x.gguf", None, 4096, backups=made)
        HL.add_section(h, "ComfyUI-Expert-x-Q4", "/c/x.gguf", None, 4096, backups=made)    # idempotent
        self.assertEqual(len(made), 1)
        with open(made[0], "rb") as f:
            self.assertEqual(f.read(), INI)
        t = self.read()
        self.assertTrue(t.startswith(INI))
        self.assertNotIn(b"\n", t.replace(b"\r\n", b""), "line ends must stay CRLF")
        self.assertTrue(HL.register_in_state(h, "ComfyUI-Expert-x-Q4", "/c/x.gguf", None, 4096, 0, made))
        # HomeAI changes the files afterwards: its changes must survive the undo
        with open(self.ini, "ab") as f:
            f.write(b"\r\n; added later by HomeAI\r\n[vision]\r\nmodel = /h/v.gguf\r\n")
        sp = os.path.join(self.d, "install.json")
        with open(sp) as f:
            st = json.load(f)
        st["models"]["vision"] = {"model": "/h/v.gguf"}
        with open(sp, "w") as f:
            json.dump(st, f)
        link = {"root": self.d, "ini": self.ini, "data": h["data"], "section": "ComfyUI-Expert-x-Q4",
                "section_added": True, "state_added": True, "preset": False, "backups": made}
        logs = []
        HL.unlink(link, logs.append)
        self.assertEqual(self.read(), INI + b"\r\n; added later by HomeAI\r\n[vision]\r\nmodel = /h/v.gguf\r\n")
        with open(sp) as f:
            self.assertEqual(sorted(json.load(f)["models"]), ["coder", "general", "vision"])
        self.assertTrue(any("backup kept" in m for m in logs))
        baks = [n for n in os.listdir(os.path.join(self.d, "engine")) if ".bak-comfy-expert-" in n]
        self.assertEqual(len(baks), 2, baks)                 # one before the add, one before the undo
        self.assertFalse([n for n in os.listdir(os.path.join(self.d, "engine")) if n.endswith(".tmp")])

    def test_undo_in_the_middle_keeps_the_next_sections_comment(self):
        h = HL.inspect(self.d)
        HL.add_section(h, "ComfyUI-Expert-y", "/c/y.gguf", "/c/mm.gguf", 0)
        with open(self.ini, "ab") as f:
            f.write(b"\r\n; keep this comment\r\n[later]\r\nmodel = /h/l.gguf\r\n")
        self.assertTrue(HL.remove_section(self.ini, "ComfyUI-Expert-y"))
        t = self.read()
        self.assertIn(b"; keep this comment\r\n[later]", t)
        self.assertNotIn(b"ComfyUI-Expert-y", t)
        self.assertNotIn(HL.MARK.encode(), t)
        self.assertFalse(HL.remove_section(self.ini, "ComfyUI-Expert-y"))      # nothing left to remove

    def test_only_our_entries_are_removed(self):
        self.assertFalse(HL.unregister_in_state(self.d, "general"))            # not added by us
        pp = os.path.join(self.d, "homeai", "data", "presets.json")
        with open(pp, "w") as f:
            json.dump([{"id": "theirs"}, {"id": HL.PRESET_ID}], f)
        self.assertTrue(HL.remove_preset(os.path.join(self.d, "homeai", "data")))
        with open(pp) as f:
            self.assertEqual(json.load(f), [{"id": "theirs"}])

    def test_damaged_homeai_files(self):
        with open(os.path.join(self.d, "install.json"), "w") as f:
            json.dump({"models": ["not", "a", "dict"]}, f)
        with open(os.path.join(self.d, "homeai", "config.json"), "w") as f:
            f.write("[]")
        h = HL.inspect(self.d)
        self.assertEqual((h["models"], h["llama_url"]), ([], "http://127.0.0.1:8081"))
        self.assertFalse(HL.unregister_in_state(self.d, "x"))
        self.assertFalse(HL.register_in_state(h, "x", "/m", None, 0))
        with self.assertRaises(RuntimeError):
            HL.add_section(dict(h, ini=None), "x", "/m", None, 0)


# ------------------------------------------------------------------------------------------------ 9. ComfyUI
class ComfyTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.saved = {k: getattr(comfyui, k) for k in ("IS_WIN", "run", "which", "_get_json")}
        self.saved_dl, self.saved_open = llamacpp.download, llamacpp._open

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(comfyui, k, v)
        llamacpp.download, llamacpp._open = self.saved_dl, self.saved_open
        shutil.rmtree(self.d, ignore_errors=True)

    def test_probe_of_odd_answers(self):
        for reply in (None, [], {"system": "x"}, {"system": {"argv": "main.py"}}, {"system": {"argv": [5]}}):
            comfyui._get_json = lambda url, timeout=3, r=reply: r
            r = comfyui.running("http://127.0.0.1:1")
            self.assertTrue(r is None or (r["root"] is None and r["version"] == "?"), repr(reply))

    def test_probe_of_a_non_json_port(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            Handler.mode = "normal"                      # answers with random bytes
            t = time.time()
            self.assertIsNone(comfyui.running("http://127.0.0.1:%d" % srv.server_address[1]))
            self.assertLess(time.time() - t, 5)
        finally:
            srv.shutdown()

    def test_bad_release_lists(self):
        for body in (b"<html>", b"{}", b"[1, null]", b'[{"draft": false, "prerelease": false}]',
                     b'[{"tag_name": "v1; rm -rf /", "draft": false}]'):
            llamacpp._open = lambda *a, b=body, **k: FakeResp(b)
            try:
                self.assertIsNone(comfyui.latest_release(), body)
            except RuntimeError:
                pass
            with self.assertRaises(RuntimeError):
                comfyui.plan({"backend": "cpu"})
        comfyui.IS_WIN = True
        llamacpp._open = lambda *a, **k: FakeResp(b'[{"tag_name": "v0.9", "assets": [{"name": "other.7z", "size": 5}]}]')
        with self.assertRaises(RuntimeError):
            comfyui.plan({"backend": "cuda", "gpu": {"vendor": "nvidia"}})

    def test_linux_never_clones_over_an_existing_folder(self):
        comfyui.IS_WIN = False
        comfyui.which = lambda n: "/usr/bin/" + n
        comfyui.run = lambda *a, **k: self.fail("must not run git")
        dest = os.path.join(self.d, "ComfyUI")
        os.makedirs(os.path.join(dest, "my-stuff"))
        with self.assertRaises(RuntimeError) as cm:
            comfyui.install(self.d, {"backend": "cpu"}, {"tag": "v0.9"}, log=lambda m: None)
        self.assertIn("not installed by this kit", str(cm.exception))
        self.assertTrue(os.path.isdir(os.path.join(dest, "my-stuff")))

    def test_linux_clone_is_verified(self):
        comfyui.IS_WIN = False
        comfyui.which = lambda n: "/usr/bin/" + n
        dest = os.path.join(self.d, "ComfyUI")

        def fake_run(cmd, timeout=60):
            if cmd[1] == "clone":
                os.makedirs(os.path.join(dest, "comfy"))
                os.makedirs(os.path.join(dest, "models"))
                open(os.path.join(dest, "main.py"), "w").close()
                return 0, ""
            if cmd[3] == "describe":
                return 0, "v0.8\n"                     # not the tag we asked for
            self.fail(cmd)
        comfyui.run = fake_run
        with self.assertRaises(RuntimeError):
            comfyui.install(self.d, {"backend": "cpu"}, {"tag": "v0.9"}, log=lambda m: None)
        self.assertFalse(os.path.exists(dest))

    def test_windows_existing_archive_is_checked_not_trusted(self):
        comfyui.IS_WIN = True
        good = b"good archive"
        a = {"name": "ComfyUI_windows_portable_nvidia.7z", "size": len(good), "browser_download_url": "http://x/a.7z",
             "digest": "sha256:" + hashlib.sha256(good).hexdigest()}
        arc = os.path.join(self.d, a["name"])
        with open(arc, "wb") as f:
            f.write(b"bad archive!")                      # same size, wrong bytes: left by a bad earlier run
        calls = []

        def fake_dl(url, dest, size, sha):
            calls.append(url)
            with open(dest, "wb") as f:
                f.write(good)
        llamacpp.download = fake_dl

        def fake_run(cmd, timeout=60):
            with open(arc, "rb") as f:
                self.assertEqual(f.read(), good)          # only a verified archive is unpacked
            c = os.path.join(self.d, "ComfyUI_windows_portable", "ComfyUI")
            for sub in ("comfy", "models"):
                os.makedirs(os.path.join(c, sub))
            open(os.path.join(c, "main.py"), "w").close()
            return 0, ""
        comfyui.run = fake_run
        logs = []
        d = comfyui.install(self.d, {"backend": "cuda"}, {"tag": "v0.9", "asset": a}, log=logs.append)
        self.assertEqual(calls, ["http://x/a.7z"])
        self.assertTrue(comfyui.kit_installed(d))
        self.assertTrue(any("does not match" in m for m in logs), logs)
        # a second run must not unpack over it, a foreign portable folder is refused
        self.assertEqual(comfyui.install(self.d, {"backend": "cuda"}, {"tag": "v0.9", "asset": a}, log=logs.append), d)
        other = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(other, "ComfyUI_windows_portable", "ComfyUI"))
            with self.assertRaises(RuntimeError):
                comfyui.install(other, {"backend": "cuda"}, {"tag": "v0.9", "asset": a}, log=logs.append)
        finally:
            shutil.rmtree(other)
        with self.assertRaises(RuntimeError):
            comfyui.install(self.d, {"backend": "cuda"}, {"tag": "v0.9", "asset": dict(a, digest="sha256:abc")})

    def test_uninstaller_never_offers_a_drive_root_or_home(self):
        self.assertTrue(uninstall._too_broad("/"))
        self.assertTrue(uninstall._too_broad(os.path.expanduser("~")))
        self.assertFalse(uninstall._too_broad(self.d))


if __name__ == "__main__":
    unittest.main()
