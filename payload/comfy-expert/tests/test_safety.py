import pytest

from comfy_expert.tools import REGISTRY, ToolError, run_tool
from comfy_expert.tools import downloads


def test_only_expected_tools_are_gated():
    gated = {n for n, t in REGISTRY.items() if t.gated}
    assert gated == {"write_workflow", "download_file", "comfy_queue_test"}
    for n in gated:
        assert REGISTRY[n].parameters["properties"]["confirm"]["default"] is False


def test_download_target_path_safety(offline_cfg):
    root = offline_cfg["models"].resolve()
    t = downloads._target("loras", "../../../evil.safetensors")
    assert root in t.parents and t.parent.name == "loras"
    with pytest.raises(ToolError):
        downloads._target("../../windows", "x.safetensors")
    with pytest.raises(ToolError):
        downloads._target("checkpoints", "a.safetensors", subfolder="../../..")
    assert root in downloads._target("checkpoints", "a.safetensors", subfolder="sdxl/real").parents


def test_download_dry_run_does_not_write(offline_cfg, monkeypatch):
    monkeypatch.setattr(downloads, "probe", lambda url: {"ok": True, "size_bytes": 1234, "size": "1.2 KB", "filename": "f.safetensors", "resumable": True})
    r = run_tool("download_file", {"url": "https://huggingface.co/a/b/resolve/main/f.safetensors", "folder": "loras"})
    assert r["dry_run"] is True
    assert not (offline_cfg["models"] / "loras" / "f.safetensors").exists()


def test_unknown_tool_and_missing_args():
    assert run_tool("nope", {})["ok"] is False
    assert "Missing" in run_tool("kb_read", {})["error"]


def test_queue_test_needs_running_comfy():
    r = run_tool("comfy_queue_test", {"source": "sdxl_txt2img", "confirm": True})
    assert r["ok"] is False and "not running" in r["error"]


def test_fixed_safety_rule_is_in_every_system_prompt(monkeypatch, tmp_path):
    """The under-18 rule lives in code, so even an emptied prompt file cannot remove it."""
    from comfy_expert.safety import SAFETY_RULE
    from comfy_expert.agent import Agent
    from comfy_expert.tools import imageprompt
    assert SAFETY_RULE in Agent().system_prompt()
    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(imageprompt, "SYSTEM_FILE", empty)
    monkeypatch.setattr(imageprompt, "REFINE_FILE", empty)
    assert imageprompt.system_prompt({}, "").startswith(SAFETY_RULE)
    assert imageprompt.refine_system_prompt({}, "").startswith(SAFETY_RULE)
