import inspect
import subprocess
import sys
from pathlib import Path

from comfy_expert.tools import REGISTRY, run_tool

ROOT = Path(__file__).resolve().parents[1]


def test_playbooks_exist():
    names = set(run_tool("kb_list", {})["playbooks"])
    assert names == {"explain_workflow", "remake_workflow", "find_models", "fix_missing_nodes", "build_from_template",
                     "troubleshoot", "compare_models", "image_to_prompt"}
    from comfy_expert.agent import ROUTES
    assert {r[1] for r in ROUTES} <= names


def test_kb_search_and_read():
    r = run_tool("kb_search", {"query": "reserve-vram AMD"})
    assert r["results"]
    assert "UK" in run_tool("kb_read", {"topic": "sites_civitai"})["text"]


def test_kb_node_names_are_real():
    import pytest
    if not (ROOT / "cache" / "extension-node-map.json").is_file():
        pytest.skip("needs cache/extension-node-map.json (downloaded by the app on first use)")
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_kb.py")], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout


def test_playbooks_only_name_real_tools():
    import re
    from comfy_expert.tools.knowledge import playbooks
    for name, p in playbooks().items():
        for t in set(re.findall(r"\b([a-z]+_[a-z_]+)\(", p.read_text())):
            assert t in REGISTRY, (name, t)


def test_mcp_wrappers_have_signatures():
    from comfy_expert.mcp_server import _make_wrapper
    for t in REGISTRY.values():
        w = _make_wrapper(t)
        sig = inspect.signature(w)
        assert set(sig.parameters) == set(t.parameters["properties"])
        if t.gated:
            assert sig.parameters["confirm"].default is False
