import json
import struct
import zlib

import pytest

from comfy_expert.tools import run_tool, wfcore
from comfy_expert.tools.comfy import get_object_info


def _png_with(text_chunks: dict) -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\x00\x00\x00"
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
    for k, v in text_chunks.items():
        out += chunk(b"tEXt", k.encode() + b"\x00" + v.encode())
    return out + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_object_info_falls_back_to_bundled():
    oi, src = get_object_info(force=True)
    assert "KSampler" in oi and src.startswith("bundled")


def test_parse_json_and_png(anime_wf):
    assert wfcore.parse_workflow_bytes(json.dumps(anime_wf).encode())["nodes"]
    png = _png_with({"workflow": json.dumps(anime_wf), "prompt": "{}"})
    wf = wfcore.parse_workflow_bytes(png, "x.png")
    assert len(wf["nodes"]) == len(anime_wf["nodes"])


def test_summarize(anime_wf):
    s = run_tool("summarize_workflow", {"source": "anime_portrait.json"})
    assert s["ok"]
    assert any("Illustrious" in f for f in s["model_family_guess"])
    assert {m["file"] for m in s["models"]} == {"waiIllustriousSDXL_v140.safetensors"}
    assert s["loras"][0]["strength"]["strength_model"] == 0.8
    assert "1girl" in s["anime_style_signals"]


def test_negative_prompt_not_style_signal():
    s = run_tool("summarize_workflow", {"source": "sdxl_txt2img"})
    assert "anime" not in s["anime_style_signals"]


def test_validate_reports_missing_models_but_no_errors():
    v = run_tool("validate_workflow", {"source": "anime_portrait.json"})
    assert v["errors"] == 0
    assert {m["file"] for m in v["missing_models"]} == {"waiIllustriousSDXL_v140.safetensors", "anime_lineart_v2.safetensors"}


def test_validate_catches_bad_node_and_bad_value(anime_wf):
    wf = json.loads(json.dumps(anime_wf))
    wf["nodes"].append({"id": 99, "type": "TotallyMadeUpNode", "pos": [0, 0], "inputs": [], "outputs": [], "widgets_values": []})
    ks = next(n for n in wf["nodes"] if n["type"] == "KSampler")
    ks["widgets_values"][4] = "not_a_sampler"
    oi, src = get_object_info()
    v = wfcore.validate(wf, oi, src)
    errs = " ".join(i["message"] for i in v["issues"] if i["level"] == "error")
    alls = " ".join(i["message"] for i in v["issues"])
    assert "TotallyMadeUpNode" in errs
    assert "not_a_sampler" in alls  # warn with the bundled list, error when ComfyUI is live


def test_edit_ops_and_original_untouched(offline_cfg):
    path = offline_cfg["workflows"] / "anime_portrait.json"
    before = path.read_text()
    r = run_tool("edit_workflow", {"source": "anime_portrait.json", "ops": [
        {"op": "set_widget", "node": 1, "widget": "ckpt_name", "value": "juggernautXL_ragnarok.safetensors"},
        {"op": "remove_node", "node": 9},
        {"op": "add_node", "type": "LoraLoader", "ref": "l2", "widgets": {"lora_name": "x.safetensors"}},
        {"op": "connect", "from": 1, "from_slot": 0, "to": "$l2", "to_input": "model"},
        {"op": "connect", "from": 1, "from_slot": 1, "to": "$l2", "to_input": "clip"},
        {"op": "connect", "from": "$l2", "from_slot": 0, "to": 4, "to_input": "model"},
        {"op": "add_note", "text": "changed"},
    ]})
    assert r["ok"], r
    assert path.read_text() == before
    v = r["validation"]
    assert v["errors"] == 0, v
    draft = r["draft_id"]
    s = run_tool("summarize_workflow", {"source": draft})
    assert s["models"][0]["found_locally"] is True


def test_remove_node_reconnects(anime_wf):
    oi, _ = get_object_info()
    new, log = wfcore.apply_ops(anime_wf, [{"op": "remove_node", "node": 9}], oi)
    v = wfcore.validate(new, oi, "bundled")
    assert v["errors"] == 0, v["issues"]


def test_bad_widget_name_is_error(anime_wf):
    with pytest.raises(wfcore.EditError):
        wfcore.apply_ops(anime_wf, [{"op": "set_widget", "node": 4, "widget": "stepz", "value": 3}])


def test_ui_to_api_templates():
    oi, _ = get_object_info()
    names = [t["name"] for t in run_tool("list_templates", {})["templates"]]
    assert len(names) == 6
    for n in names:
        s = run_tool("validate_workflow", {"source": n})
        assert s["errors"] == 0, (n, s["issues"])
        from comfy_expert.tools.workflow import load_any
        wf, _ = load_any(n)
        api = wfcore.ui_to_api(wf, oi)
        for nid, node in api.items():
            info = oi[node["class_type"]]
            for k in (info.get("input", {}).get("required") or {}):
                assert k in node["inputs"], (n, nid, node["class_type"], k)


def test_dynamic_combo_slots():
    oi, _ = get_object_info()
    slots = wfcore.widget_slots("ResizeImageMaskNode", oi, ["scale dimensions", 512, 512])
    assert slots[0] == "resize_type"
    assert any(s.startswith("resize_type.") for s in slots)


def test_write_workflow_gating_and_no_overwrite(offline_cfg):
    d = run_tool("edit_workflow", {"source": "sdxl_txt2img", "ops": [{"op": "set_widget", "node": 4, "widget": "steps", "value": 25}]})
    dry = run_tool("write_workflow", {"draft_id": d["draft_id"], "filename": "../../evil name"})
    assert dry["dry_run"] is True
    gen = offline_cfg["workflows"] / "generated"
    assert not gen.exists() or not list(gen.iterdir())
    w1 = run_tool("write_workflow", {"draft_id": d["draft_id"], "filename": "../../evil name", "confirm": True})
    w2 = run_tool("write_workflow", {"draft_id": d["draft_id"], "filename": "../../evil name", "confirm": True})
    from pathlib import Path
    p1, p2 = Path(w1["written"]), Path(w2["written"])
    assert p1.parent == gen and p2.parent == gen and p1 != p2
    assert json.loads(p1.read_text())["nodes"]


def test_write_refuses_invalid():
    d = run_tool("edit_workflow", {"source": "sdxl_txt2img", "ops": [{"op": "add_node", "type": "KSampler"}]})
    r = run_tool("write_workflow", {"draft_id": d["draft_id"], "filename": "bad", "confirm": True})
    assert r["ok"] is False and "error" in r["error"]


def test_official_template_dir_absent_is_handled():
    r = run_tool("list_official_templates", {"match": "flux"})
    assert "ok" in r


def test_node_by_title_and_single_widget_alias(anime_wf):
    oi, _ = get_object_info()
    new, _log = wfcore.apply_ops(anime_wf, [{"op": "set_widget", "node": "positive_prompt", "widget": "value", "value": "photo"}], oi)
    assert next(n for n in new["nodes"] if n["id"] == 2)["widgets_values"][0] == "photo"
    new, _log = wfcore.apply_ops(anime_wf, [{"op": "set_widget", "node": "KSampler", "widget": "cfg", "value": 4.5}], oi)
    assert next(n for n in new["nodes"] if n["id"] == 4)["widgets_values"][3] == 4.5
    # ambiguous type -> error that lists the real ids
    with pytest.raises(wfcore.EditError, match="Nodes: 1=CheckpointLoaderSimple"):
        wfcore.apply_ops(anime_wf, [{"op": "set_widget", "node": "CLIPTextEncode", "widget": "text", "value": "x"}], oi)


def test_prompt_alias_never_hits_other_widgets(anime_wf):
    oi, _ = get_object_info()
    with pytest.raises(wfcore.EditError):
        wfcore.apply_ops(anime_wf, [{"op": "set_widget", "node": 1, "widget": "positive_prompt", "value": "photo"}], oi)
