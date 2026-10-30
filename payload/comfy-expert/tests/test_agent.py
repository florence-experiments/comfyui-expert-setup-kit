import json

from comfy_expert import agent as agent_mod
from comfy_expert.agent import Agent, Session, _visible, route


def test_router():
    assert route("look at my workflow and recreate it with more realistic characters") == "remake_workflow"
    assert route("I get out of memory on wan 2.2") == "troubleshoot"
    assert route("my workflow has red nodes") == "fix_missing_nodes"
    assert route("find me a realistic SDXL lora") == "find_models"
    assert route("compare juggernaut vs realvis") == "compare_models"
    assert route("explain this workflow") == "explain_workflow"
    assert route("hello") is None


def test_visible_hides_think_and_toolcall():
    assert _visible("<think>secret") == ""
    assert _visible("<think>a</think>Hello") == "Hello"
    assert _visible('Hi <tool_call>{"name":"x"}') == "Hi "


def test_parse_fallback_tool_call():
    text, calls = Agent.parse_tool_calls({"content": '<think>hm</think>ok <tool_call>{"name": "kb_list", "arguments": {}}</tool_call>'})
    assert calls[0]["name"] == "kb_list" and text == "ok"
    text, calls = Agent.parse_tool_calls({"content": "", "tool_calls": [{"id": "1", "function": {"name": "kb_read", "arguments": "{bad"}}]})
    assert "__invalid_json__" in calls[0]["args"]


class Scripted(Agent):
    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.sent = []

    def _complete(self, messages, use_tools=True, turn=None):
        self.sent.append(messages)
        yield {"message": self.replies.pop(0)}


def tc(name, args):
    return {"role": "assistant", "content": "", "tool_calls": [{"id": "c" + name, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_loop_runs_tools_and_finishes():
    a = Scripted([tc("kb_search", {"query": "reserve-vram"}), {"role": "assistant", "content": "Use `--reserve-vram 2`."}])
    s = Session()
    evs = list(a.chat(s, "how much vram should I reserve?"))
    types = [e["type"] for e in evs]
    assert "tool_call" in types and "tool_result" in types and types[-1] == "final"
    assert s.messages[-1]["content"].startswith("Use")


def test_confirm_flow_yes_and_no(offline_cfg):
    d = Agent().__class__  # noqa
    from comfy_expert.tools import run_tool
    draft = run_tool("edit_workflow", {"source": "sdxl_txt2img", "ops": [{"op": "set_widget", "node": 4, "widget": "steps", "value": 20}]})["draft_id"]
    a = Scripted([tc("write_workflow", {"draft_id": draft, "filename": "t1", "confirm": True}),
                  {"role": "assistant", "content": "Saved."},
                  tc("write_workflow", {"draft_id": draft, "filename": "t2", "confirm": True}),
                  {"role": "assistant", "content": "OK, not saved."}])
    s = Session()
    evs = list(a.chat(s, "save it"))
    assert evs[-1]["type"] == "confirm" and s.pending
    gen = offline_cfg["workflows"] / "generated"
    assert not gen.exists()
    evs = list(a.resume(s, True))
    assert any(e["type"] == "tool_result" and e["result"].get("written") for e in evs)
    assert (gen / "t1.json").exists()
    evs = list(a.chat(s, "save another"))
    assert evs[-1]["type"] == "confirm"
    evs = list(a.resume(s, False))
    assert any(e["type"] == "tool_result" and e["result"].get("declined_by_user") for e in evs)
    assert not (gen / "t2.json").exists()


def test_self_check_asks_for_verification_then_flags():
    fake = "Download https://huggingface.co/fake/repo/resolve/main/made_up_model.safetensors and add `MadeUpNodeXYZ`."
    a = Scripted([{"role": "assistant", "content": fake}, {"role": "assistant", "content": fake}])
    s = Session()
    evs = list(a.chat(s, "what should I download?"))
    st = [e for e in evs if e["type"] == "status" and "Self-check" in e["text"]]
    assert st and any("MadeUpNodeXYZ" in i for i in st[0]["items"])
    fin = evs[-1]
    assert fin["type"] == "final" and "Not verified" in fin["text"] and fin["unverified"]


def test_self_check_passes_verified_items():
    a = Scripted([tc("comfy_node_info", {"node_type": "KSampler"}), {"role": "assistant", "content": "Use `KSampler` with juggernautXL_ragnarok.safetensors."}])
    s = Session()
    s.evidence.append("juggernautXL_ragnarok.safetensors")
    evs = list(a.chat(s, "which sampler node?"))
    assert evs[-1]["type"] == "final" and not evs[-1]["unverified"]


def test_trim_keeps_pairs():
    a = Agent()
    a.llm["context_size"] = 16000
    msgs = []
    for i in range(30):
        msgs += [{"role": "user", "content": "q" * 50}, tc("kb_list", {}), {"role": "tool", "tool_call_id": "ckb_list", "content": "x" * 5000}]
    out = a._trim(msgs)
    assert out[0]["role"] == "user"
    assert sum(len(m.get("content") or "") for m in out) < sum(len(m.get("content") or "") for m in msgs)


def test_llm_unreachable_gives_helpful_error():
    a = Agent()
    a._model = None
    evs = list(a.chat(Session(), "hi"))
    assert evs[-1]["type"] == "error" and "llama-server" in evs[-1]["text"]


def test_gated_call_not_offered_when_it_would_fail(offline_cfg):
    # a batch edit(fails) + write(confirm) must not ask the user; a bogus draft must not ask either
    a = Scripted([{"role": "assistant", "content": "", "tool_calls": [
                     {"id": "e", "type": "function", "function": {"name": "edit_workflow", "arguments": json.dumps(
                         {"source": "anime_portrait.json", "ops": [{"op": "set_widget", "node": 99, "widget": "x", "value": 1}]})}},
                     {"id": "w", "type": "function", "function": {"name": "write_workflow", "arguments": json.dumps(
                         {"draft_id": "nope", "filename": "x", "confirm": True})}}]},
                  tc("write_workflow", {"draft_id": "nope", "filename": "x", "confirm": True}),
                  {"role": "assistant", "content": "Could not save."}])
    s = Session()
    evs = list(a.chat(s, "edit and save"))
    assert not any(e["type"] == "confirm" for e in evs) and not s.pending
    assert evs[-1]["type"] == "final"
    assert not (offline_cfg["workflows"] / "generated").exists()


def test_repeated_failing_call_is_blocked():
    bad = {"source": "does_not_exist.json"}
    a = Scripted([tc("summarize_workflow", bad), tc("summarize_workflow", bad), tc("summarize_workflow", bad),
                  {"role": "assistant", "content": "That file does not exist."}])
    evs = list(a.chat(Session(), "explain it"))
    res = [e["result"] for e in evs if e["type"] == "tool_result"]
    assert "already made exactly this call 2 times" in res[2]["error"]


def test_repeated_successful_call_loop_is_stopped():
    q = {"query": "reserve-vram"}
    a = Scripted([tc("kb_search", q)] * 5 + [{"role": "assistant", "content": "Done."}])
    evs = list(a.chat(Session(), "vram?"))
    res = [e["result"] for e in evs if e["type"] == "tool_result"]
    assert "Loop detected" in res[3]["error"] and evs[-1]["type"] == "final"


def test_loop_guard_forces_final_answer():
    q = {"query": "reserve-vram"}
    a = Scripted([tc("kb_search", q)] * 6 + [{"role": "assistant", "content": "Here is what I found."}])
    evs = list(a.chat(Session(), "vram?"))
    assert any(e["type"] == "status" and "Loop guard" in e["text"] for e in evs)
    assert evs[-1]["type"] == "final"
    assert len([e for e in evs if e["type"] == "tool_result"]) == 5


def test_same_gated_action_never_asked_twice(offline_cfg):
    from comfy_expert.tools import run_tool
    draft = run_tool("edit_workflow", {"source": "sdxl_txt2img", "ops": [{"op": "set_widget", "node": 4, "widget": "steps", "value": 20}]})["draft_id"]
    w = {"draft_id": draft, "filename": "once", "confirm": True}
    a = Scripted([tc("write_workflow", w), tc("write_workflow", w), {"role": "assistant", "content": "Saved once."}])
    s = Session()
    list(a.chat(s, "save"))
    evs = list(a.resume(s, True))
    assert not any(e["type"] == "confirm" for e in evs) and evs[-1]["type"] == "final"
    assert [p.name for p in (offline_cfg["workflows"] / "generated").iterdir()] == ["once.json"]
