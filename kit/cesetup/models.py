"""Model choice: the recommended model (the one the app was built and tested with), a model found by a
Hugging Face search sized to this computer, a model HomeAI already has, or a GGUF file already on disk."""
from __future__ import annotations

import os
import re

from . import hfcore as H, hfsearch as S
from .util import GiB, gib, say

# The model ComfyUI Expert was developed with (uncensored 'abliterated' Qwen3.8 27B, small IQ3_XXS quant with a
# built-in MTP head for faster replies) plus its vision add-on, so Prompt Artist can look at pictures.
RECOMMENDED = {
    "repo": "huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF",
    "name": "Huihui-Qwen3.8-27B-abliterated (IQ3_XXS, MTP) + vision add-on",
    "quant": "IQ3_XXS",
    "params_b": 27, "ctx": 32768, "mtp": True, "uncensored": True,
    "files": [{"path": "Huihui-Qwen3.8-27B-abliterated-GSQ-RCO-IQ3_XXS-mtp.gguf", "size": 10442827296,
               "sha256": "53fbcda56fae73e1bc2f3222f6939b4cf051fc52c26acc387b4c90f6da7d5c7d"}],
    "mmproj": {"path": "mmproj-model-bf16.gguf", "size": 931145888,
               "sha256": "c9a09064683620bea3d3bfed5d4462e1a97a7d2fff7e5045d6862a0a85eeb5b5"},
    "sampling": ["--temp", "1.0", "--top-p", "0.95", "--top-k", "20", "--min-p", "0"],
}
RECOMMENDED["url"] = "https://huggingface.co/" + RECOMMENDED["repo"]
RECOMMENDED["download_gib"] = round(gib(sum(f["size"] for f in RECOMMENDED["files"]) + RECOMMENDED["mmproj"]["size"]), 2)

# Test hook (CE_KIT_TEST_TINY=1): a ~100 MB model, so the whole install can be tested quickly.
TINY = {"repo": "bartowski/SmolLM2-135M-Instruct-GGUF", "name": "SmolLM2-135M-Instruct (test model)", "quant": "Q4_K_M",
        "params_b": 0.135, "ctx": 8192, "mtp": False, "uncensored": False,
        "files": [{"path": "SmolLM2-135M-Instruct-Q4_K_M.gguf", "size": None, "sha256": None}], "mmproj": None,
        "url": "https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF", "download_gib": 0.1, "sampling": []}


def recommended_fit(hw):
    """Plain-English note on how the recommended model fits this computer."""
    b = S.Budget(hw, {"ctx": 32768, "disk_budget_gib": 999})
    weights = sum(f["size"] for f in RECOMMENDED["files"])
    kv = int(32768 * 64 * 1024)          # ~2 GiB of q8_0 KV for 32k on this hybrid 27B (rough)
    f = S.plan_fit(b, weights, kv, RECOMMENDED["mmproj"]["size"], True, 27, None, None)
    return f


def fill_tiny(hf):
    t = dict(TINY, files=[dict(TINY["files"][0])])
    for f in hf.tree(t["repo"]):
        if f.get("path") == t["files"][0]["path"]:
            t["files"][0]["size"] = (f.get("lfs") or {}).get("size") or f.get("size")
            t["files"][0]["sha256"] = (f.get("lfs") or {}).get("oid")
    t["download_gib"] = round(gib(t["files"][0]["size"] or 0), 2)
    return t


def search(hf, hw, uncensored=True, top_n=4):
    res, errs = S.Searcher(hf, hw, {"ctx": 32768, "speed": "balanced", "uncensored": uncensored,
                                     "disk_budget_gib": max(5.0, hw.get("disk_free_gib", 50) - 10)}, say).run("expert", top_n=top_n)
    out = []
    for ch in res:
        if ch["repo"] == RECOMMENDED["repo"]:
            continue
        ch = S.fill_sizes(hf, ch)
        out.append({"repo": ch["repo"], "name": ch["name"], "quant": ch["quant"], "params_b": ch["params_b"],
                    "ctx": max(32768, int(ch.get("ctx") or 32768)), "files": ch["files"], "mmproj": ch["mmproj"],
                    "url": ch["url"], "download_gib": ch["download_gib"], "n_cpu_moe": ch.get("n_cpu_moe", 0),
                    "mtp": False, "uncensored": ch.get("uncensored"), "sampling": [], "_desc": S.describe_choice(0, ch)})
    return out, errs


def model_dir(root, repo):
    return os.path.join(root, "models", re.sub(r"[^A-Za-z0-9._-]+", "_", repo.replace("/", "__")))


def download(hf, root, choice):
    """Downloads every file of the choice (resumable, SHA-256 checked). Returns (ok, model_path, mmproj_path)."""
    d = model_dir(root, choice["repo"])
    paths = []
    for f in choice["files"]:
        ok, p = H.download_file(hf, choice["repo"], f["path"], d, f.get("size"), f.get("sha256"))
        if not ok:
            return False, None, None
        paths.append(p)
    mm = None
    if choice.get("mmproj"):
        m = choice["mmproj"]
        ok, mm = H.download_file(hf, choice["repo"], m["path"], d, m.get("size"), m.get("sha256"))
        if not ok:
            say("   the vision add-on could not be downloaded - Prompt Artist will not be able to see pictures")
            mm = None
    return True, sorted(paths)[0], mm


def local_gguf(path):
    """A GGUF the user already has. Reads its header to check it is a real GGUF."""
    if not path or not os.path.isfile(path) or not path.lower().endswith(".gguf"):
        return None
    with open(path, "rb") as fh:
        meta = H.parse_gguf_header(fh.read(4 * 1024 * 1024))
    if not meta.get("general.architecture"):
        return None
    d = os.path.dirname(path)
    mm = next((os.path.join(d, n) for n in sorted(os.listdir(d)) if "mmproj" in n.lower() and n.lower().endswith(".gguf")), None)
    return {"model": path, "mmproj": mm, "arch": meta.get("general.architecture"), "gib": round(os.path.getsize(path) / GiB, 2)}
