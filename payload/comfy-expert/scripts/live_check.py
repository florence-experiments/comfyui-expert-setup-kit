"""Live smoke test of the network tools (needs internet; ComfyUI optional). Prints PASS/FAIL per check.
Usage: python scripts/live_check.py"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfy_expert.tools import load_all, run_tool  # noqa: E402

load_all()
CHECKS = [
    ("web_search", {"query": "ComfyUI Qwen-Image-Edit 2511 GGUF workflow", "max_results": 5}, lambda r: len(r.get("results", [])) >= 2),
    ("fetch_url", {"url": "https://docs.comfy.org/", "max_chars": 2000}, lambda r: len(r.get("text", "")) > 200),
    ("github_search", {"query": "ComfyUI-GGUF", "max_results": 3}, lambda r: any("gguf" in x.get("repo", x.get("url", "")).lower() for x in r.get("results", []))),
    ("find_node_pack", {"node_type": "FaceDetailer"}, lambda r: any("Impact-Pack" in m["repo"] for m in r.get("exact_matches", []))),
    ("find_node_pack", {"node_type": "UnetLoaderGGUF"}, lambda r: any("GGUF" in m["repo"] for m in r.get("exact_matches", []))),
    ("civitai_search_models", {"query": "juggernaut xl", "types": ["Checkpoint"], "limit": 5}, lambda r: len(r.get("models") or r.get("results") or []) >= 1),
    ("civitai_get_model", {"model_id": 133005}, lambda r: "Juggernaut" in json.dumps(r)),
    ("civitai_by_hash", {"sha256": "dd08fa32"}, lambda r: True),  # short hash -> expect a clear error or result, not a crash
    ("model_archive_search", {"query": "realistic", "platform": "seaart", "limit": 3}, lambda r: r.get("ok") is not False),
    ("hf_search_models", {"query": "Qwen-Image-Edit-2511", "filter": "gguf", "limit": 5}, lambda r: len(r.get("models") or r.get("results") or []) >= 1),
    ("hf_list_files", {"repo": "unsloth/Qwen-Image-Edit-2511-GGUF", "match": "Q4_K_M"}, lambda r: any("Q4_K_M" in json.dumps(f) for f in r.get("files", []))),
    ("hf_model_info", {"repo": "Comfy-Org/Qwen-Image_ComfyUI"}, lambda r: r.get("ok") is not False),
    ("comfy_status", {}, lambda r: r.get("ok") is not False),
    ("comfy_node_info", {"node_type": "KSampler"}, lambda r: "sampler_name" in json.dumps(r)),
    ("list_official_templates", {"match": "qwen edit", "limit": 5}, lambda r: True),
]
fails = 0
for name, args, ok in CHECKS:
    t = time.time()
    r = run_tool(name, args)
    good = bool(r.get("ok", True) is not False or name == "civitai_by_hash") and ok(r)
    fails += not good
    extra = r.get("error") or r.get("source") or r.get("note") or ""
    print(f"{'PASS' if good else 'FAIL'}  {name:24s} {time.time() - t:5.1f}s  {str(extra)[:110]}")
print(f"\n{len(CHECKS) - fails}/{len(CHECKS)} passed")
sys.exit(1 if fails else 0)
