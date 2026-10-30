"""ComfyUI Expert agent: OpenAI-style tool-calling loop against a local llama-server.

The agent is an event generator so the CLI, the web UI and tests can all drive it:
    for ev in agent.chat(session, "explain my workflow"): ...
Events (dicts with "type"):
    status        {"text"}                      - progress info
    thinking      {"text"}                      - model reasoning (if the server separates it)
    assistant     {"text"}                      - text the model said alongside tool calls
    delta         {"text"}                      - streamed token text (final answer or pre-tool text)
    tool_call     {"id","name","args","gated"}
    tool_result   {"id","name","result","short"}
    confirm       {"id","name","args","summary"} - STOP: needs agent.resume(session, approved)
    final         {"text","unverified":[...]}
    error         {"text"}
"""
from __future__ import annotations

import json
import platform
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import requests

from .config import APP_DIR, load_config
from .safety import with_safety_rule
from .tools import REGISTRY, load_all, run_tool

THINK_RE = re.compile(r"<think>.*?</think>", re.S)
TOOLCALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
URL_RE = re.compile(r"https?://[^\s)\]>\"'`,]+")
FILE_RE = re.compile(r"[\w\-.+\[\]()]+\.(?:safetensors|gguf|ckpt|pth|pt|bin|onnx|sft)\b", re.I)
NODE_RE = re.compile(r"`([A-Z][A-Za-z0-9_]*[a-z][A-Za-z0-9_]*)`")

IMAGE_FILE_RE = re.compile(r"Image file:\s*(.+?\.(?:png|jpe?g|webp|bmp|gif))\s*$", re.I | re.M)
REFERENCE_FILE_RE = re.compile(r"Reference file:\s*(.+?\.(?:png|jpe?g|webp|bmp|gif))\s*$", re.I | re.M)
# fix mode: the uploaded image is a RESULT the user generated, not a new reference
PA_FIX_RE = re.compile(r"\b(prompt artist fix|fix my result|fix (this|it|the result)|refine|my result|what went wrong|"
                       r"(it|this) came out|still wrong|didn'?t work|did not work|generated (this|it|image)|wrong (colou?r|hair|eyes|pose))\b", re.I)
PA_FIXED_RE = re.compile(r"^\W*(yes\W+)?((that|this|it)\s+(fixed it|worked|works|did it)|(it'?s\s+)?fixed( it)?|perfect|nailed it|"
                         r"that'?s (it|right|perfect))\b", re.I)
PA_FAILED_RE = re.compile(r"^\W*(still wrong|(it |that )?(didn'?t|did not|doesn'?t) (work|fix)|not fixed|no (change|better)|worse)\b", re.I)

ROUTES: list[tuple[str, str]] = [
    (r"\b(prompt artist|image.?to.?prompt|prompt (for|from) (this|the|an?|my) (image|picture|pic|photo)|tag (this|the) (image|picture))\b", "image_to_prompt"),
    (r"\b(remake|recreate|redo|convert|turn .* into|more realistic|realistic version|anime.?to.?real|change (the )?style|restyle|refresh(ed)? workflow)\b", "remake_workflow"),
    (r"\b(red nodes?|missing nodes?|not found node|node types? (were )?not found|install missing|missing custom)\b", "fix_missing_nodes"),
    (r"\b(oom|out of memory|error|failed|crash|black image|nan|slow|not working|broken|traceback|hip|allocation)\b", "troubleshoot"),
    (r"\b(compare|vs\.?|versus|which (model|checkpoint|lora) is better|best (model|checkpoint|lora))\b", "compare_models"),
    (r"\b(template|from scratch|build (me )?a (new )?workflow|create (a )?(new )?workflow|make (me )?a workflow)\b", "build_from_template"),
    (r"\b(download|which models?)\b|\b(find|get|suggest|recommend|look for|search)\b.*\b(models?|checkpoints?|loras?|upscalers?|controlnets?|vae|gguf)\b", "find_models"),
    (r"\b(explain|what does .* do|summari[sz]e|describe|walk me through|understand) .*\bworkflow|\bworkflow\b.*\b(explain|summary)\b", "explain_workflow"),
]


def route(text: str) -> str | None:
    low = text.lower()
    for pat, name in ROUTES:
        if re.search(pat, low):
            return name
    return None


SYSTEM_PROMPT = """You are **ComfyUI Expert**, a local assistant that knows ComfyUI, its workflows, custom nodes and model sites (Civitai, Hugging Face, Tensor.Art, SeaArt, CivArchive and mirrors). You run on the user's own PC and have TOOLS. Use them.

## Golden rules
1. NEVER state a node type, model file name, download URL, repo, setting or version as fact unless a tool returned it in this conversation (or the user said it). If you have not verified something, verify it with a tool or say clearly "(not verified)". Don't guess links - search (civitai_search_models / hf_search_models / hf_list_files / model_archive_search / web_search / fetch_url).
2. Node names: check with comfy_node_info (exact class names and widget names). Missing nodes: find_node_pack.
3. Workflows: read with summarize_workflow / read_workflow. Change them ONLY through edit_workflow (makes a draft copy). The result includes validation - fix every error before saving. Never modify the user's existing files; write_workflow always saves a NEW file in the 'generated' folder. Nodes are addressed by their numeric id (summarize_workflow/read_workflow show them). edit_workflow returns a draft_id - wait for it, then pass THAT draft_id to validate_workflow / write_workflow (do one step per message when a step needs an earlier result). If a search finds nothing, retry at most once with shorter keywords (no file extension), then tell the user it was not found - do not repeat the same searches. A file that is missing locally does not have to be found before editing; only search when the user wants it.
4. Read-only by default. write_workflow, download_file and comfy_queue_test change things: first call them with confirm=false (dry run) and show the user what will happen, then call with confirm=true - the user gets a Yes/No button. If the user says no, accept it.
5. Prefer copying and editing a verified starter: list_templates (this helper's) or list_official_templates (ComfyUI's own templates, with wiring and download links that are known to work) over inventing JSON.
6. Knowledge pack: kb_search / kb_read for settings, model families, AMD tips, sites; get_playbook for step lists. Facts there are verified; still check exact file names with tools.
7. NSFW is allowed (adult user, own hobby) but every character must be an adult. See the FIXED SAFETY RULE at the top: it always applies.
8. The user's PC: {hardware}. Prefer GGUF/fp8 for big models, warn when something won't fit or needs CUDA-only libraries.
9. Be concise and practical. Plain English, short lists, exact file names, folders and links. When a task has many steps, do them with tools instead of telling the user to do them, except installs (tell them how).
10. Call tools with valid JSON arguments only; one step at a time is fine. If a tool errors, read the error and fix the call.

## Environment
- Date: {today}. Host OS: {os}.
- ComfyUI API: {comfy_url}  | ComfyUI folder: {comfy_root}
- Model folders: {model_roots}
- Workflow folders: {workflow_dirs}  (new files go to: {generated})
- Civitai is region-blocked in some countries (e.g. the UK): civitai_* tools fall back to CivArchive + mirror links automatically. Always verify a mirror by sha256 when available.
"""

SELF_CHECK_MSG = """[self-check by ComfyUI Expert - not from the user]
Your answer mentions items that no tool result in this conversation confirmed:
{items}
Before answering: verify them with tools (e.g. hf_list_files, civitai_get_model, comfy_node_info, find_node_pack, fetch_url) OR remove them OR clearly mark them "(not verified)". Then give your final answer again (complete, not just the corrections)."""


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    messages: list[dict] = field(default_factory=list)   # without the system prompt
    evidence: list[str] = field(default_factory=list)    # tool results + user text, for self-check
    pending: dict | None = None                          # waiting for confirm
    self_checked: bool = False
    failed: dict = field(default_factory=dict)            # call key -> [times failed, last error]
    calls: dict = field(default_factory=dict)             # call key -> times made (loop guard)
    gated_done: dict = field(default_factory=dict)        # gated call key -> result (approved or declined)
    blocked: int = 0                                      # calls blocked by the loop guard in the last round
    created: float = field(default_factory=time.time)
    title: str = ""
    pa: dict = field(default_factory=dict)                # Prompt Artist state: reference, last answer, family, pending lessons
    # saved chats (data/chats): what the screen shows, a user-chosen title, last change
    display: list[dict] = field(default_factory=list)
    title_custom: bool = False
    updated: float = 0.0

    def to_json(self) -> dict:
        return {"id": self.id, "title": self.title, "created": self.created, "messages": self.messages}


class LLMError(Exception):
    pass


class Agent:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        load_all()
        self.llm = self.cfg["llm"]
        self._model: str | None = self.llm.get("model") or None
        self.http = requests.Session()
        self._known_nodes: set[str] | None = None

    # ------------------------------------------------------------- LLM
    @property
    def base(self) -> str:
        return self.llm["base_url"].rstrip("/")

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.llm.get('api_key') or 'local'}", "Content-Type": "application/json"}

    def model(self) -> str:
        if self._model:
            return self._model
        try:
            r = self.http.get(self.base + "/models", headers=self.headers(), timeout=10)
            data = r.json().get("data") or []
            self._model = data[0]["id"] if data else "local-model"
        except Exception as e:
            raise LLMError(f"Cannot reach llama-server at {self.base} ({type(e).__name__}). "
                           "Start it first, e.g.: llama-server -m <model.gguf> --jinja -c 32768 -ngl 99 --port 8080") from e
        return self._model

    def server_context(self) -> int | None:
        """Ask llama-server for its real context size (/props)."""
        try:
            root = self.base[:-3] if self.base.endswith("/v1") else self.base
            r = self.http.get(root + "/props", timeout=5)
            gs = r.json().get("default_generation_settings") or {}
            n = int(gs.get("n_ctx") or r.json().get("n_ctx") or 0) or None
            if n:
                self._server_ctx = n
            return n
        except Exception:
            return None

    def tool_schemas(self) -> list[dict]:
        return [t.openai_schema() for t in REGISTRY.values()]

    def system_prompt(self) -> str:
        c = self.cfg
        return with_safety_rule(SYSTEM_PROMPT.format(
            today=date.today().isoformat(), os=platform.system() + " " + platform.release(),
            comfy_url=c["comfyui"]["url"], comfy_root=c.comfy_root,
            model_roots=", ".join(str(p) for p in c.model_roots()) or "(none)",
            workflow_dirs=", ".join(str(p) for p in c.workflow_dirs()) or "(none)",
            generated=c.generated_dir(),
            hardware=(c.get("hardware") or {}).get("summary") or "unknown (ask the user if it matters)"))

    def _complete(self, messages: list[dict], use_tools: bool = True, body: dict | None = None,
                  base: str | None = None) -> Iterator[dict]:
        """Yields {"delta": str} / {"thinking": str} while streaming and finally {"message": {...}}.
        body/base: send a ready request body to another endpoint (used by Prompt Artist for the vision model)."""
        if body is None:
            body = {"model": self.model(), "messages": messages, "temperature": self.llm.get("temperature", 0.3),
                    "max_tokens": self.llm.get("max_tokens", 4096), "stream": bool(self.llm.get("stream", True))}
            if use_tools:
                body["tools"] = self.tool_schemas()
                body["tool_choice"] = "auto"
        try:
            r = self.http.post((base or self.base) + "/chat/completions", headers=self.headers(), json=body,
                               timeout=self.llm.get("timeout", 900), stream=body["stream"])
        except requests.RequestException as e:
            raise LLMError(f"llama-server request failed: {e}") from e
        if r.status_code != 200:
            txt = r.text[:800]
            hint = ""
            if "exceed" in txt.lower() and "context" in txt.lower():
                hint = " (Context too small - restart llama-server with a bigger -c, e.g. -c 32768, or start a new chat.)"
            elif "tools" in txt.lower() and "jinja" in txt.lower():
                hint = " (Start llama-server with --jinja so tool calling works.)"
            raise LLMError(f"llama-server HTTP {r.status_code}: {txt}{hint}")
        if not body["stream"]:
            msg = r.json()["choices"][0]["message"]
            yield {"message": msg}
            return
        content, reasoning, calls = [], [], {}
        for raw in r.iter_lines(decode_unicode=False):
            if not raw:
                continue
            line = raw.decode("utf-8", "replace")
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except ValueError:
                continue
            if "error" in chunk:
                raise LLMError(f"llama-server error: {chunk['error']}")
            for ch in chunk.get("choices") or []:
                d = ch.get("delta") or {}
                if d.get("reasoning_content"):
                    reasoning.append(d["reasoning_content"])
                    yield {"thinking": d["reasoning_content"]}
                if d.get("content"):
                    content.append(d["content"])
                    yield {"delta": d["content"]}
                for tc in d.get("tool_calls") or []:
                    i = tc.get("index", len(calls))
                    slot = calls.setdefault(i, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]
        msg = {"role": "assistant", "content": "".join(content)}
        if reasoning:
            msg["reasoning_content"] = "".join(reasoning)
        if calls:
            msg["tool_calls"] = [calls[k] for k in sorted(calls)]
        yield {"message": msg}

    # ------------------------------------------------------------- helpers
    @staticmethod
    def parse_tool_calls(msg: dict) -> tuple[str, list[dict]]:
        """Return (clean_text, calls[{id,name,args}]) handling text-embedded <tool_call> fallbacks."""
        text = msg.get("content") or ""
        text = THINK_RE.sub("", text)
        if "<think>" in text and "</think>" not in text:   # unterminated reasoning
            text = text.split("<think>")[0]
        if "</think>" in text:
            text = text.split("</think>", 1)[1]
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except ValueError:
                    args = {"__invalid_json__": args}
            calls.append({"id": tc.get("id") or "call_" + uuid.uuid4().hex[:8], "name": fn.get("name", ""), "args": args or {}})
        if not calls:
            for m in TOOLCALL_RE.finditer(text):
                try:
                    obj = json.loads(m.group(1))
                except ValueError:
                    continue
                name = obj.get("name")
                if name:
                    args = obj.get("arguments") or obj.get("parameters") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = {}
                    calls.append({"id": "call_" + uuid.uuid4().hex[:8], "name": name, "args": args})
            if calls:
                text = TOOLCALL_RE.sub("", text)
        return text.strip(), calls

    def _known_node_names(self) -> set[str]:
        if self._known_nodes is None:
            names: set[str] = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode"}
            try:
                from .tools.comfy import get_object_info
                oi, _ = get_object_info()
                names |= set(oi)
            except Exception:
                pass
            f = APP_DIR / "cache" / "extension-node-map.json"
            if f.exists():
                try:
                    for _, val in json.loads(f.read_text(encoding="utf-8")).items():
                        names.update(val[0])
                except Exception:
                    pass
            self._known_nodes = names
        return self._known_nodes

    def unverified(self, session: Session, text: str) -> list[str]:
        ev = "\n".join(session.evidence)
        ev_low = ev.lower()
        out = []
        for u in set(URL_RE.findall(text)):
            u2 = u.rstrip(".;:!?")
            if u2.lower() in ev_low or u2.rstrip("/").lower() in ev_low:
                continue
            # allow well-known site roots without paths (e.g. https://civitai.com)
            if re.fullmatch(r"https?://[^/]+/?", u2):
                continue
            if "127.0.0.1" in u2 or "localhost" in u2 or "host.docker.internal" in u2:
                continue
            out.append(f"URL {u2}")
        for f in set(FILE_RE.findall(text)):
            if f.lower() in ev_low:
                continue
            out.append(f"file name {f}")
        known = self._known_node_names()
        for n in set(NODE_RE.findall(text)):
            if n in known or n in ev:
                continue
            out.append(f"node type {n}")
        return sorted(out)

    def context_size(self) -> int:
        """The configured context (-c), or llama-server's real one when that is smaller
        (known once server_context() has been asked, e.g. by the web UI's status check)."""
        ctx = int(self.llm.get("context_size") or 32768)
        real = getattr(self, "_server_ctx", None)
        return real if real and real < ctx else ctx

    def _trim(self, messages: list[dict]) -> list[dict]:
        """Keep the prompt inside the context window: shrink old tool results, then drop old turns.
        Only the copy sent to the model is trimmed; the saved chat keeps every message.
        Sets self.trimmed_turns to the number of whole turns left out."""
        self.trimmed_turns = 0
        ctx = self.context_size()
        budget_chars = int((ctx - int(self.llm.get("max_tokens", 4096))) * 3.0) - 26000  # ~ tool schemas + system
        budget_chars = max(budget_chars, 8000)

        def size(ms):
            return sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or "")) for m in ms)

        ms = [dict(m) for m in messages]
        if size(ms) <= budget_chars:
            return ms
        last_user = max((i for i, m in enumerate(ms) if m["role"] == "user"), default=0)
        for i, m in enumerate(ms):
            if i >= last_user:
                break
            if m["role"] == "tool" and len(m.get("content") or "") > 600:
                m["content"] = m["content"][:500] + " ... [older tool result shortened to save context]"
        while size(ms) > budget_chars:
            users = [i for i, m in enumerate(ms) if m["role"] == "user"]
            if len(users) < 2:
                break
            ms = ms[users[1]:]   # drop the oldest whole turn
            self.trimmed_turns += 1
        if size(ms) > budget_chars:  # still too big within the current turn: shrink its older tool results
            tools_idx = [i for i, m in enumerate(ms) if m["role"] == "tool"]
            for i in tools_idx[:-2]:
                if len(ms[i].get("content") or "") > 1500:
                    ms[i]["content"] = ms[i]["content"][:1200] + " ... [shortened to fit the context window]"
        return ms

    def _result_text(self, name: str, res: dict) -> str:
        s = json.dumps(res, ensure_ascii=False, default=str)
        lim = int(self.llm.get("max_tool_result_chars", 9000))
        if len(s) > lim:
            s = s[:lim] + f' ... [truncated {len(s) - lim} chars; ask for less, e.g. use match/limit/offset]'
        return s

    @staticmethod
    def _short(res: dict) -> str:
        if not res.get("ok", True):
            return "error: " + str(res.get("error", ""))[:160]
        keys = [k for k in res if k != "ok"][:6]
        return ", ".join(keys)

    # ------------------------------------------------------------- main loop
    def chat(self, session: Session, user_text: str) -> Iterator[dict]:
        if session.pending:
            yield {"type": "error", "text": "Please answer the pending Yes/No question first."}
            return
        if not session.title:
            session.title = user_text.strip().splitlines()[0][:60] if user_text.strip() else "chat"
        img = IMAGE_FILE_RE.search(user_text)
        if session.pa.get("pending") and not img and PA_FIXED_RE.search(user_text):
            yield from self._pa_feedback(session, user_text, worked=True)
            return
        if session.pa.get("pending") and PA_FAILED_RE.search(user_text):
            if not img:
                yield from self._pa_feedback(session, user_text, worked=False)
                return
            self._pa_mark(session, worked=False)
        if img and (route(user_text) == "image_to_prompt" or PA_FIX_RE.search(user_text)
                    or not re.search(r"\bworkflow\b", user_text, re.I)):
            mode = "fix" if PA_FIX_RE.search(user_text) else "analyse"
            yield from self._prompt_artist(session, user_text, img.group(1).strip(), mode)
            return
        content = user_text
        pb = route(user_text)
        if pb:
            from .tools.knowledge import playbooks
            p = playbooks().get(pb)
            if p:
                content += (f"\n\n[ComfyUI Expert note: this looks like the '{pb}' task. Suggested playbook:]\n"
                            + p.read_text(encoding="utf-8"))
                yield {"type": "status", "text": f"Using playbook: {pb}"}
        session.messages.append({"role": "user", "content": content})
        session.evidence.append(user_text)
        session.self_checked = False
        yield from self._loop(session)

    def resume(self, session: Session, approved: bool) -> Iterator[dict]:
        p = session.pending
        if not p:
            yield {"type": "error", "text": "Nothing is waiting for confirmation."}
            return
        session.pending = None
        call = p["call"]
        if approved:
            yield {"type": "status", "text": f"Approved: {call['name']}"}
            res = run_tool(call["name"], call["args"])
        else:
            res = {"ok": False, "declined_by_user": True,
                   "message": "The user said NO. Do not retry this action; ask what they want instead or continue without it."}
        session.gated_done[self._key(call)] = res
        yield from self._emit_result(session, call, res)
        yield from self._run_calls(session, p["remaining"])
        if session.pending:
            return
        yield from self._loop(session)

    def _emit_result(self, session: Session, call: dict, res: dict) -> Iterator[dict]:
        txt = self._result_text(call["name"], res)
        session.messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": txt})
        session.evidence.append(txt)
        yield {"type": "tool_result", "id": call["id"], "name": call["name"], "result": res, "short": self._short(res)}

    def _run_calls(self, session: Session, calls: list[dict]) -> Iterator[dict]:
        seen: dict[str, dict] = {}
        batch_failed = False
        session.blocked = 0
        for k, call in enumerate(calls):
            t = REGISTRY.get(call["name"])
            if "__invalid_json__" in call["args"]:
                res = {"ok": False, "error": "Your tool arguments were not valid JSON. Send a JSON object.",
                       "received": str(call["args"]["__invalid_json__"])[:300]}
                yield from self._emit_result(session, call, res)
                continue
            key = self._key(call)
            session.calls[key] = session.calls.get(key, 0) + 1
            if session.calls[key] > 3 and key not in seen:  # same call again and again = the model is looping
                session.blocked += 1
                res = {"ok": False, "error": f"Loop detected: you have made exactly this call {session.calls[key] - 1} times already "
                       "and the result will not change. Stop searching for this and tell the user what you found (or did not find)."}
                yield from self._emit_result(session, call, res)
                continue
            if session.failed.get(key, [0])[0] >= 2:  # stop small models looping on the exact same failing call
                session.blocked += 1
                res = {"ok": False, "error": f"You already made exactly this call {session.failed[key][0]} times and it failed: "
                       + session.failed[key][1][:400] + " - change the arguments, or explain the problem to the user, instead of repeating it."}
                yield from self._emit_result(session, call, res)
                continue
            if t and t.gated and call["args"].get("confirm") is True:
                if key in session.gated_done:  # never ask twice for the same action
                    prev = session.gated_done[key]
                    res = {"ok": False, "error": "Already " + ("declined by the user" if prev.get("declined_by_user") else "done")
                           + " earlier in this chat - not asking again. Previous result: " + json.dumps(prev, default=str)[:400]}
                    yield from self._emit_result(session, call, res)
                    continue
                if batch_failed:
                    res = {"ok": False, "error": "Not run: an earlier tool call in this same message failed. "
                           "Fix that first, then call this again (one step at a time)."}
                    yield from self._emit_result(session, call, res)
                    continue
                # Dry run first (always safe): only ask the user when the action can actually work.
                dry = run_tool(call["name"], {**call["args"], "confirm": False})
                if dry.get("ok") is False:
                    self._note_fail(session, key, dry)
                    yield from self._emit_result(session, call, {**dry, "note": "Checked with a dry run before asking the user; it would fail, so the user was not asked."})
                    continue
                session.pending = {"call": call, "remaining": calls[k + 1:]}
                yield {"type": "confirm", "id": call["id"], "name": call["name"], "args": call["args"],
                       "summary": self._confirm_summary(call), "preview": dry}
                return
            if key in seen:  # small models sometimes repeat the same call in one message
                res = {"ok": True, "note": "Same call as the previous one in this message - see that result."}
            else:
                res = run_tool(call["name"], call["args"])
                seen[key] = res
            if isinstance(res, dict) and res.get("ok") is False:
                batch_failed = True
                self._note_fail(session, key, res)
            yield from self._emit_result(session, call, res)

    @staticmethod
    def _key(call: dict) -> str:
        return call["name"] + json.dumps(call["args"], sort_keys=True, default=str)

    @staticmethod
    def _note_fail(session: Session, key: str, res: dict) -> None:
        n = session.failed.get(key, [0, ""])[0]
        session.failed[key] = [n + 1, str(res.get("error"))]

    @staticmethod
    def _confirm_summary(call: dict) -> str:
        a = call["args"]
        n = call["name"]
        if n == "download_file":
            return f"Download {a.get('filename') or a.get('url')} into models/{a.get('folder')}{'/' + a['subfolder'] if a.get('subfolder') else ''} from {a.get('url')}"
        if n == "write_workflow":
            return f"Save draft {a.get('draft_id')} as a NEW workflow file '{a.get('filename')}' (in the 'generated' folder)"
        if n == "comfy_queue_test":
            return f"Queue a test generation in ComfyUI from {a.get('source')}"
        return f"Run {n} with {json.dumps(a)[:300]}"

    # ------------------------------------------------------------- Prompt Artist (image -> prompt)
    def _vision_stream(self, ep: dict, messages: list[dict]) -> Iterator[dict]:
        from .tools import imageprompt
        body = imageprompt.request_body(ep, messages, stream=True)
        yield from self._complete(messages, use_tools=False, body=body, base=ep["base_url"])

    def _prompt_artist(self, session: Session, user_text: str, image: str, mode: str = "analyse") -> Iterator[dict]:
        """Send the image straight to the vision model with the Prompt Artist instructions and stream the answer.
        mode 'analyse': a new reference image -> analysis, best family, prompts.
        mode 'fix': a RESULT the user generated (+ the reference / earlier prompt from this chat) -> diagnosis, corrected
        prompt, changelog and tentative lessons (confirmed later by "This fixed it").
        The answer stays in the chat, so follow-ups ("make it Pony", "more explicit") go through the normal agent."""
        from .tools import ToolError, imageprompt, lessons
        pa = session.pa
        fix = mode == "fix"
        yield {"type": "status", "text": "Prompt Artist: " + ("comparing your result with the target" if fix
                                                               else "reading the image and your installed checkpoints")}
        notes = REFERENCE_FILE_RE.sub("", IMAGE_FILE_RE.sub("", user_text))
        notes = re.sub(r"(?i)prompt artist( fix)?:?|analy[sz]e this image and write the best prompt to recreate it\.?|"
                       r"here is the image i generated[^\n]*", "", notes).strip()
        notes = re.sub(r"(?im)^note:\s*", "", notes).strip()
        try:
            img = imageprompt.resolve_image(image)
            inv = imageprompt.inventory()
            ep = imageprompt.pick_endpoint()
            if fix:
                ref_m = REFERENCE_FILE_RE.search(user_text)
                ref = imageprompt.resolve_image(ref_m.group(1).strip()) if ref_m else (
                    Path(pa["reference"]) if pa.get("reference") and Path(pa["reference"]).is_file() else None)
                if ref is not None and ref.resolve() == img.resolve():
                    ref = None
                meta = imageprompt.generation_metadata(img)
                fam_hint = pa.get("family") or ""
                ck_hint = pa.get("checkpoint") or ((meta.get("models") or [""])[0])
                ltxt = lessons.as_text(lessons.relevant(fam_hint, ck_hint, 10))
                msgs = imageprompt.build_refine_messages(img, ref, _pa_prompt_section(pa.get("answer", "")), notes, inv,
                                                         ltxt, "\n".join(pa.get("failed", [])[-3:]))
            else:
                ref = None
                ltxt = lessons.as_text(lessons.relevant("", "", 8))
                msgs = imageprompt.build_messages(img, notes, inv, ltxt)
        except ToolError as e:
            yield {"type": "error", "text": str(e)}
            return
        yield {"type": "status", "text": f"Prompt Artist: asking the vision model at {ep['base_url']}"
               + (" (result + reference)" if fix and ref is not None else "")}
        raw, shown, msg = "", "", None
        try:
            for ev in self._vision_stream(ep, msgs):
                if "delta" in ev:
                    raw += ev["delta"]
                    vis = _visible(raw)
                    cut = re.search(r"(\n#{2,4}\s*Lessons\s*\n)?```\s*lessons", vis, re.I)
                    if cut:
                        vis = vis[:cut.start()]
                    if len(vis) > len(shown) and vis.startswith(shown):
                        yield {"type": "delta", "text": vis[len(shown):]}
                        shown = vis
                elif "thinking" in ev:
                    yield {"type": "thinking", "text": ev["thinking"]}
                else:
                    msg = ev["message"]
        except LLMError as e:
            yield {"type": "error", "text": f"Vision model: {e}"}
            return
        text = THINK_RE.sub("", (msg or {}).get("content") or raw).strip()
        if "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        if not text:
            yield {"type": "error", "text": "The vision model returned an empty answer."}
            return
        saved: list[dict] = []
        if fix:
            text, found = lessons.parse_block(text)
            fam, ck = _pa_family(text)
            for l in found[:3]:
                l.setdefault("family", fam or pa.get("family", ""))
                if not l.get("checkpoint"):
                    l["checkpoint"] = ck or pa.get("checkpoint", "")
                try:
                    r = lessons.add(l, session=session.id)
                except OSError:
                    r = None
                if r:
                    saved.append(r)
            if saved:
                text += ("\n\n📝 Saved " + str(len(saved)) + " tentative lesson(s) for " + saved[0]["family"]
                         + ". Generate with the corrected prompt, then click **✅ This fixed it** (or reply \"that fixed it\") "
                         "and I'll remember them as confirmed. If it's still wrong, click **❌ Still wrong** or upload the new result with 🔧.")
            pa["pending"] = [l["id"] for l in saved]
            pa["attempts"] = pa.get("attempts", 0) + 1
        else:
            pa.clear()
            pa["reference"] = str(img)
        fam, ck = _pa_family(text)
        if fam:
            pa["family"] = fam
        if ck:
            pa["checkpoint"] = ck
        pa["answer"] = text
        inv_txt = imageprompt.inventory_text(inv)
        label = "Prompt Artist fix: the RESULT image was compared" + (" with the reference" if fix and ref is not None else "") \
            if fix else "Prompt Artist: the image was analysed by the vision model"
        session.messages.append({"role": "user", "content": user_text + f"\n\n[{label}. Installed models:]\n" + inv_txt})
        session.evidence += [user_text, inv_txt, text]
        session.messages.append({"role": "assistant", "content": text})
        yield {"type": "final", "text": text, "unverified": [],
               "pa": {"mode": mode, "lessons": [l["id"] for l in saved], "family": pa.get("family", "")}}

    def _pa_mark(self, session: Session, worked: bool) -> list[dict]:
        from .tools import lessons
        ids = session.pa.get("pending") or []
        done = (lessons.confirm if worked else lessons.reject)(ids) if ids else []
        if not worked and session.pa.get("answer"):
            session.pa.setdefault("failed", []).append(_pa_changelog(session.pa["answer"]))
        session.pa["pending"] = []
        return done

    def _pa_feedback(self, session: Session, user_text: str, worked: bool) -> Iterator[dict]:
        """'That fixed it' / 'still wrong' after a fix: confirm or reject the pending lessons (no model call needed)."""
        try:
            done = self._pa_mark(session, worked)
        except OSError as e:
            yield {"type": "error", "text": f"Could not update the lessons file: {e}"}
            return
        if worked:
            lines = "\n".join(f"- **{l['family']}**: {l['symptom']} → {l['fix']}" for l in done)
            text = (f"🎉 Great! I saved {len(done)} lesson(s) as **confirmed**. I'll use them in future prompts for this model family:\n"
                    + lines) if done else "🎉 Great! (There were no new lessons to confirm.)"
        else:
            text = ("Noted. Those fixes didn't work, so I won't suggest them again. Upload the new result with **🔧 Fix my result** "
                    "(add a note about what is still wrong) and I'll try the next most likely cause.")
        session.messages.append({"role": "user", "content": user_text})
        session.messages.append({"role": "assistant", "content": text})
        yield {"type": "final", "text": text, "unverified": [], "pa": {"mode": "feedback", "lessons": []}}

    def _loop(self, session: Session) -> Iterator[dict]:
        rounds = int(self.llm.get("max_tool_rounds", 30))
        stuck, no_tools = 0, False
        for _ in range(rounds):
            hist = self._trim(session.messages)
            sysp = self.system_prompt()
            if self.trimmed_turns:
                sysp += (f"\n## Long chat\nThis is a long saved chat: its {self.trimmed_turns} oldest turn(s) are left out here "
                         "to fit the context window. If the user refers to something you cannot see, say so and ask them to repeat it.\n")
            msgs = [{"role": "system", "content": sysp}] + hist
            msg = None
            raw, shown = "", ""
            try:
                for ev in self._complete(msgs, use_tools=not no_tools):
                    if "delta" in ev:
                        raw += ev["delta"]
                        vis = _visible(raw)
                        if not vis.startswith(shown):
                            yield {"type": "retract"}
                            shown = ""
                        if len(vis) > len(shown):
                            yield {"type": "delta", "text": vis[len(shown):]}
                            shown = vis
                    elif "thinking" in ev:
                        yield {"type": "thinking", "text": ev["thinking"]}
                    else:
                        msg = ev["message"]
            except LLMError as e:
                yield {"type": "error", "text": str(e)}
                return
            if msg is None:
                yield {"type": "error", "text": "Empty reply from llama-server."}
                return
            if msg.get("reasoning_content") and not self.llm.get("stream", True):
                yield {"type": "thinking", "text": msg["reasoning_content"]}
            text, calls = self.parse_tool_calls(msg)
            if no_tools:
                calls = []
            if calls:
                hist = {"role": "assistant", "content": text,
                        "tool_calls": [{"id": c["id"], "type": "function",
                                        "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                                       for c in calls]}
                session.messages.append(hist)
                if text:
                    yield {"type": "assistant", "text": text}
                for c in calls:
                    t = REGISTRY.get(c["name"])
                    yield {"type": "tool_call", "id": c["id"], "name": c["name"], "args": c["args"], "gated": bool(t and t.gated)}
                yield from self._run_calls(session, calls)
                if session.pending:
                    return
                stuck = stuck + 1 if session.blocked >= len(calls) else 0
                if stuck >= 2:  # the model ignores the loop warnings: make it answer without tools
                    no_tools = True
                    session.messages.append({"role": "user", "content": "(system) You are repeating tool calls that are blocked. "
                                             "Tools are now OFF. Tell the user plainly what you did, what worked, what failed and why, "
                                             "and what they could ask next. Do not invent results."})
                    yield {"type": "status", "text": "Loop guard: the model kept repeating the same calls - asking it to sum up"}
                continue
            # final answer
            if not text:
                text = "(The model returned an empty answer. Try rephrasing, or check the llama-server console.)"
            if self.llm.get("self_check", True) and not session.self_checked:
                bad = self.unverified(session, text)
                if bad:
                    session.self_checked = True
                    session.messages.append({"role": "assistant", "content": text})
                    session.messages.append({"role": "user", "content": SELF_CHECK_MSG.format(items="\n".join(f"- {b}" for b in bad[:25]))})
                    yield {"type": "status", "text": f"Self-check: {len(bad)} unverified item(s) - asking the model to verify them", "items": bad}
                    yield {"type": "retract"}
                    continue
            bad = self.unverified(session, text) if self.llm.get("self_check", True) else []
            if bad:
                text += "\n\n> ⚠ Not verified by a tool in this chat (double-check before using): " + "; ".join(bad[:15])
            session.messages.append({"role": "assistant", "content": text})
            yield {"type": "final", "text": text, "unverified": bad}
            return
        yield {"type": "error", "text": f"Stopped after {rounds} tool rounds. Ask me to continue if needed."}


def _visible(raw: str) -> str:
    """Text safe to show while streaming: hides <think> blocks and <tool_call> blocks (also unfinished ones)."""
    v = THINK_RE.sub("", raw)
    if "</think>" in v:
        v = v.split("</think>", 1)[1]
    for tag in ("<think>", "<tool_call>"):
        if tag in v:
            v = v.split(tag, 1)[0] if tag == "<think>" else TOOLCALL_RE.sub("", v).split(tag, 1)[0]
    # hold back a possible partial tag at the end
    m = re.search(r"<[a-z_/]*$", v)
    if m:
        v = v[:m.start()]
    return v.lstrip()


def _pa_family(text: str) -> tuple[str, str]:
    """(family, checkpoint file) from a Prompt Artist answer's prompt heading."""
    m = re.search(r"#{2,4}\s*(?:\d\.\s*)?(?:Prompt for|Corrected prompt)\s*\(?\s*([^(\n,]+?)\s*[(,]\s*`?([^`)\n]+?)`?\s*\)", text or "", re.I)
    if not m:
        return "", ""
    fam, ck = m.group(1).strip(" *`"), m.group(2).strip(" *`")
    return fam, (ck if FILE_RE.search(ck) else "")


def _pa_prompt_section(text: str) -> str:
    """The prompt + settings part of a Prompt Artist answer (to send back in fix mode)."""
    m = re.search(r"(#{2,4}\s*(?:\d\.\s*)?(?:Prompt for|Corrected prompt).*?)(?=\n#{2,4}\s*(?:\d\.\s*)?(?:Runner-up|Changelog|Tips|If that)|\Z)",
                  text or "", re.S | re.I)
    return (m.group(1) if m else "")[:6000]


def _pa_changelog(text: str) -> str:
    m = re.search(r"#{2,4}\s*(?:\d\.\s*)?Changelog\s*\n(.*?)(?=\n#{2,4}|\Z)", text or "", re.S | re.I)
    return (m.group(1).strip() if m else _pa_prompt_section(text))[:1500]


def save_session(session: Session) -> Path:
    d = APP_DIR / "cache" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{session.id}.json"
    p.write_text(json.dumps(session.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")
    return p
