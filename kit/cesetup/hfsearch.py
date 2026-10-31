"""Find GGUF models on Hugging Face that suit ComfyUI Expert and this computer.

Same approach as the HomeAI Setup Kit: GGUF repos only, quant picked per file, GGUF header read with a small HTTP range
request for an exact KV-cache estimate, fit check against VRAM / RAM, MoE expert offload (n-cpu-moe), mmproj for
vision, refusal numbers from model cards. Nothing is downloaded here: this only returns suggestions."""
from __future__ import annotations

import concurrent.futures as cf
import math
import os
import re

from . import hfcore as H
from .modes import MODES
from .util import GiB, gib

UNCENSORED_KEYWORDS = ["abliterated", "abliteration", "ablit", "uncensored", "heretic", "heresy", "decensored",
                       "de-censored", "no-refusal", "no-refusals", "norefusal", "refusal-free", "unrefused",
                       "derestricted", "unfiltered", "unaligned", "orthogonalized", "mpoa"]
WEAK_KEYWORDS = ["nsfw"]
TRUSTED = ["bartowski", "mradermacher", "unsloth", "lmstudio-community", "ggml-org", "QuantFactory", "mlabonne",
           "p-e-w", "TheDrummer", "Qwen", "google", "mistralai", "microsoft", "ibm-granite", "nvidia", "allenai",
           "openai", "deepseek-ai"]
EXCLUDE = ["-mlx", "mlx-", "-awq", "-gptq", "-exl2", "-exl3", "-onnx", "lora", "-4bit", "-8bit", "embedding",
           "reranker", "text-encoder", "draft", "-eagle", "dflash", "nvfp4", "-fp8", "rocmfpx", "ninfer"]
# quants: the best one (highest bits) that fits is chosen, but never above the cap of the user's speed/quality choice
QUANT_CAP = {"fast": 4.9, "balanced": 5.7, "quality": 6.6}
GPU_BW_GBS = {"nvidia": 450, "amd": 400, "intel": 250, None: 0}    # rough dedicated-GPU memory bandwidth guess
CPU_BW_GBS = 35


def hf_client(cache_dir, token=None):
    return H.HF({"allowed_hosts": ["huggingface.co", "hf.co"], "token": token, "cache_dir": cache_dir,
                 "cache_hours": 6}, use_cache=bool(cache_dir))


def _search(hf, term, author, sort, limit):
    params = [("filter", "gguf"), ("sort", sort), ("direction", "-1"), ("limit", str(limit))]
    if term:
        params.insert(0, ("search", term))
    if author:
        params.append(("author", author))
    params += [("expand[]", x) for x in hf.EXPAND]
    d = hf.get_json("/api/models", params)
    return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []


def read_header(hf, repo, path):
    url = hf.file_url(repo, path)
    meta = {}
    for size in (2 * 1024 * 1024, 12 * 1024 * 1024):
        meta = H.parse_gguf_header(hf.get_range(url, 0, size - 1))
        a = meta.get("general.architecture")
        if a and meta.get(a + ".block_count") and (meta.get(a + ".attention.head_count_kv") is not None
                                                    or not meta.get("_truncated")):
            break
    return meta


class Budget:
    """What this computer can hold. hw = scan() result; prefs = interview answers."""

    def __init__(self, hw, prefs):
        self.backend = hw.get("backend", "cpu")
        self.vendor = (hw.get("gpu") or {}).get("vendor") if self.backend != "cpu" else None
        vram = float(hw.get("vram_gib") or 0) if self.backend != "cpu" else 0.0
        ram = float(hw.get("ram_gib") or 8)
        self.gpu = max(0.0, vram - (1.2 if hw.get("os") == "windows" else 0.8)) if vram else 0.0
        self.ram = max(1.0, ram - max(4.0, ram * 0.25))
        self.disk = float(prefs.get("disk_budget_gib") or 50)
        self.ctx = int(prefs.get("ctx") or 32768)
        self.speed = prefs.get("speed", "balanced")
        self.uncensored = prefs.get("uncensored", True)

    def describe(self):
        return "GPU budget %.1f GiB, RAM budget %.1f GiB, disk budget %.0f GiB, context %d" % (
            self.gpu, self.ram, self.disk, self.ctx)


def plan_fit(b, weights, kv, mm, vision, params_b, active_b, info):
    """-> dict(fits, where, need_gib, gpu_gib, ram_gib, n_cpu_moe, tps, note)."""
    oh = 0.5 + (gib(mm) + 0.6 if vision else 0)
    W, K = gib(weights), gib(kv)
    act = active_b or params_b or 8
    frac_active = min(1.0, act / params_b) if params_b else 1.0
    if b.gpu > 0:
        if W + K + oh <= b.gpu:
            bw = GPU_BW_GBS.get(b.vendor, 300)
            return dict(fits=True, where="all on the graphics card", need=W + K + oh, gpu=W + K + oh, ram=0, n_cpu_moe=0,
                        tps=max(1, 0.7 * bw / max(0.3, W * frac_active * 1.074)))
        experts = (info or {}).get("experts")
        n_layer = int((info or {}).get("n_layer") or 0)
        if experts and active_b and n_layer:
            expert_share = max(0.5, 1.0 - frac_active * 1.3)       # most MoE weight lives in the experts
            dense_part = W * (1 - expert_share)
            per_layer_experts = W * expert_share / n_layer
            room = b.gpu - dense_part - K - oh
            if room > -per_layer_experts * 0.5:
                n_cpu = min(n_layer, max(0, math.ceil((W * expert_share - max(0.0, room)) / per_layer_experts)))
                ram_need = per_layer_experts * n_cpu
                if ram_need <= b.ram:
                    cpu_frac = n_cpu / n_layer
                    t_gpu = W * frac_active * (1 - cpu_frac) / (0.7 * GPU_BW_GBS.get(b.vendor, 300))
                    t_cpu = W * frac_active * cpu_frac / (0.6 * CPU_BW_GBS)
                    return dict(fits=True, where="graphics card + %d expert layers in system RAM" % n_cpu,
                                need=W + K + oh, gpu=W + K + oh - ram_need, ram=ram_need, n_cpu_moe=n_cpu,
                                tps=max(1, 1 / max(1e-3, t_gpu + t_cpu)))
        if W + K + oh <= b.gpu + b.ram:
            on_gpu = max(0.0, b.gpu - K - oh) / W
            t = W * on_gpu / (0.7 * GPU_BW_GBS.get(b.vendor, 300)) + W * (1 - on_gpu) / (0.6 * CPU_BW_GBS)
            return dict(fits=True, where="split: %d%% on the graphics card, rest in system RAM (slower)" % (100 * on_gpu),
                        need=W + K + oh, gpu=b.gpu, ram=W * (1 - on_gpu), n_cpu_moe=0, tps=max(0.5, 1 / max(1e-3, t)),
                        partial=True)
        return dict(fits=False, where="too big", need=W + K + oh, gpu=0, ram=0, n_cpu_moe=0, tps=0)
    need = W + K + 0.5 + (gib(mm) + 0.6 if vision else 0)
    if need <= b.ram:
        return dict(fits=True, where="processor and system RAM (no usable graphics card)", need=need, gpu=0, ram=need,
                    n_cpu_moe=0, tps=max(0.5, 0.6 * CPU_BW_GBS / max(0.3, W * frac_active)))
    return dict(fits=False, where="too big for system RAM", need=need, gpu=0, ram=0, n_cpu_moe=0, tps=0)


def _quant_bonus(bits):
    if not bits:
        return -2
    return -8 if bits < 3.3 else -4 if bits < 4.0 else 0 if bits < 5.0 else 1.5 if bits < 6.0 else 2 if bits < 7.0 else 2.5


class Searcher:
    def __init__(self, hf, hw, prefs, log=print):
        self.hf, self.hw, self.prefs, self.log = hf, hw, prefs, log
        self.b = Budget(hw, prefs)
        self.cfg = {"uncensored_keywords": UNCENSORED_KEYWORDS, "weak_keywords": WEAK_KEYWORDS}
        self.trusted = {t.lower() for t in TRUSTED}

    # 1. gather
    def gather(self, mode_key):
        m = MODES[mode_key]
        qs = []
        if self.b.uncensored:
            for term, author in m["search_uncensored"]:
                if "{u}" in term:
                    qs += [(term.replace("{u}", u).strip(), author) for u in ("abliterated", "uncensored", "heretic")]
                else:
                    qs.append((term, author))
        else:
            qs = list(m["search_standard"])
        seen = {}
        jobs = [(t, a, "downloads", 40) for t, a in qs] + [(t, a, "lastModified", 25) for t, a in qs[:4]]
        with cf.ThreadPoolExecutor(4) as ex:
            for res in ex.map(lambda j: _search(self.hf, *j), jobs):
                for info in res or []:
                    if isinstance(info.get("id"), str) and "/" in info["id"] and info["id"] not in seen:
                        seen[info["id"]] = info
        self.log("  looked at %d Hugging Face repos (%d searches)" % (len(seen), len(jobs)))
        return [H.Cand(i) for i in seen.values()]

    # 2. cheap filter + score
    def prefilter(self, mode_key, cands):
        m = MODES[mode_key]
        avoid, prefer = re.compile(m["avoid"]), re.compile(m["prefer"])
        best = {}
        for c in cands:
            low = c.id.lower()
            if any(p in low for p in EXCLUDE) or avoid.search(low):
                continue
            strong, weak = H.uncensored_evidence(c, self.cfg)
            if self.b.uncensored:
                if not strong and mode_key not in ("caption",) and not re.search(r"roleplay|writer|creative", low):
                    continue
            elif strong:
                continue
            c.evidence = strong + ["(weak) " + w for w in weak]
            if not c.size_b or c.size_b < 0.5:
                continue
            est = c.size_b * 0.56 * 1e9 / GiB         # ~Q4_K_M weights
            if est > self.b.gpu + self.b.ram or est > self.b.disk:
                continue
            if m.get("min_ctx") and c.api_ctx and c.api_ctx < m["min_ctx"]:
                continue
            c.prefer = bool(prefer.search(low))
            c.pre = self.prescore(c)
            k = c.origin_key
            if k not in best or c.pre > best[k].pre:
                if k in best:
                    c.also.append(best[k].id)
                best[k] = c
        return sorted(best.values(), key=lambda c: c.pre, reverse=True)

    def prescore(self, c):
        s = 3 * math.log10(c.downloads + 1) + math.log10(c.likes + 1)
        s += 10 * math.log2(max(1.0, min(c.size_b, self._size_cap())))
        if c.size_b > self._size_cap():
            s -= 6 * math.log2(c.size_b / self._size_cap())
        age = H.days_since(c.modified)
        if age is not None:
            s += 3 if age < 90 else 1 if age < 365 else -3 if age > 720 else 0
        if getattr(c, "prefer", False):
            s += 6
        if c.author.lower() in self.trusted:
            s += 3
        if c.evidence and not c.evidence[0].startswith("(weak)"):
            s += 2
        return s

    def _size_cap(self):
        """Largest sensible model (billions of params) for this machine at ~Q4."""
        room = self.b.gpu if self.b.gpu > 0 else self.b.ram
        if self.b.gpu > 0 and self.b.ram > 16:
            room += 0.35 * self.b.ram           # MoE offload can use some RAM
        cap = max(1.0, room / 0.62)
        return cap * (0.6 if self.b.speed == "fast" else 1.0)

    # 3. detail: files, header, fit, card
    def detail(self, mode_key, c):
        m = MODES[mode_key]
        vision = bool(m.get("vision"))
        try:
            tree = self.hf.tree(c.id)
            quants, mmprojs = H.pick_files(tree, c.size_b)
            if not quants:
                c.ok = False; c.warnings.append("no usable GGUF files"); return c
            mm = H.pick_mmproj(mmprojs)
            c.has_vision = bool(mm)
            if vision and not mm:
                c.ok = False; c.warnings.append("no image encoder (mmproj) file"); return c
            # header from a mid-size quant (all quants share the metadata)
            q0 = sorted(quants.values(), key=lambda e: abs((e["bpw"] or 5) - 4.8))[0]
            c.header = read_header(self.hf, c.id, q0["files"][0])
            info = H.arch_info(c.header)
            c.arch = (info or {}).get("arch") or c.api_arch
            ctx_train = int((info or {}).get("ctx_train") or c.api_ctx or 0)
            want = self.b.ctx
            if m.get("min_ctx"):
                want = max(want, m["min_ctx"])
            ctx = min(want, ctx_train) if ctx_train else want
            c.ctx = ctx
            if ctx_train and ctx_train < want:
                c.warnings.append("trained for %d tokens of context (you asked for %d)" % (ctx_train, want))
            kv, c.kv_note = H.kv_estimate(info, ctx, "q8_0", "q8_0", c.size_b)
            c.kv = kv
            cap = QUANT_CAP.get(self.b.speed, 5.7)
            floor = 3.3 if c.size_b >= 20 else 3.9 if c.size_b >= 8 else 4.4
            opts = sorted([e for e in quants.values() if (e["bpw"] or 0) >= floor and (e["bpw"] or 99) <= cap + 0.05],
                          key=lambda e: e["bpw"], reverse=True)
            if not opts:
                opts = sorted(quants.values(), key=lambda e: abs((e["bpw"] or 5) - 4.8))[:1]
            mm_size = (mm or {}).get("size", 0) if vision else 0
            chosen, fit, fallback = None, None, None
            for e in opts:
                f = plan_fit(self.b, e["size"], kv, mm_size, vision, c.size_b, c.active_b, info)
                if not f["fits"] or gib(e["size"] + mm_size) > self.b.disk:
                    continue
                if f.get("partial"):
                    fallback = fallback or (e, f)
                    continue
                chosen, fit = e, f
                break
            if not chosen and fallback:
                chosen, fit = fallback
                c.warnings.append("does not fully fit on the graphics card: part runs from system RAM, so it is slower")
            if not chosen:
                c.ok = False; c.warnings.append("too big for this computer at %d context" % ctx); return c
            c.quant, c.files, c.fit = chosen["quant"], chosen, fit
            c.size = chosen["size"]
            c.bpw = chosen["bpw"]
            if vision or (mm and MODES[mode_key].get("want_vision")):
                c.mmproj = mm
        except Exception as ex:  # one bad repo must not stop the search
            c.ok = False
            c.warnings.append("could not read repo: %s" % ex)
            return c
        try:  # card evidence is a bonus: a card that cannot be read does not drop an otherwise good model
            c.stats = H.card_stats(self.hf.readme(c.id))
            for bm in c.base_models[:2]:
                if not c.stats.get("refusals") and "/" in bm:
                    for k, v in H.card_stats(self.hf.readme(bm)).items():
                        c.stats.setdefault(k, v)
        except Exception:
            c.stats = c.stats if isinstance(c.stats, dict) else {}
        return c

    def score(self, mode_key, c):
        """Only candidates that detail() fully filled in get a score; anything else is marked not ok and skipped."""
        f = c.fit
        if not c.ok or not isinstance(f, dict) or not f.get("fits") or not isinstance(c.files, dict) \
                or not c.files.get("files") or not isinstance(f.get("tps"), (int, float)):
            c.ok = False
            return c
        s = getattr(c, "pre", 0.0)
        R, W = c.reasons, c.warnings
        s += 12 * math.log2(max(0.5, c.size_b or 0.5)) * 0.5 + _quant_bonus(getattr(c, "bpw", None)) * (
            2 if self.b.speed == "quality" else 1)
        tps = f["tps"]
        pen = -15 if tps < 5 else -8 if tps < 10 else -3 if tps < 20 else 0
        s += pen * (2 if self.b.speed == "fast" else 0.5 if self.b.speed == "quality" else 1)
        st = c.stats or {}
        if self.b.uncensored:
            if st.get("refusals"):
                a, b = st["refusals"]
                R.append("model card reports %d/%d refusals in its test" % (a, b))
                s += 6 if st["refusal_rate"] <= 0.05 else 2 if st["refusal_rate"] <= 0.12 else -6
            if c.evidence:
                R.append("described as: " + ", ".join(c.evidence[:3]))
        if st.get("needs_fork_hint"):
            W.append("model card mentions a patched llama.cpp - may not load"); s -= 20
        if c.author.lower() in self.trusted:
            R.append("from a well-known uploader (%s)" % c.author)
        R.append("%s downloads, %s likes" % (f"{c.downloads:,}", c.likes))
        R.insert(0, "runs on: %s, about %d words/s (rough guess)" % (f.get("where", "?"), max(1, round(tps * 0.75))))
        c.score = round(s, 1)
        return c

    def run(self, mode_key, top_n=3, max_detail=10):
        self.log("Searching Hugging Face for %s models (%s)..." % (MODES[mode_key]["label"], "uncensored" if self.b.uncensored else "standard"))
        self.log("  " + self.b.describe())
        kept = self.prefilter(mode_key, self.gather(mode_key))
        top = kept[:max_detail]
        self.log("  checking files and memory fit of the %d most promising..." % len(top))
        with cf.ThreadPoolExecutor(4) as ex:
            done = list(ex.map(lambda c: self.detail(mode_key, c), top))
        scored = [self.score(mode_key, c) for c in done if c.ok]
        good = sorted((c for c in scored if c.ok), key=lambda c: c.score, reverse=True)
        return [to_choice(mode_key, c) for c in good[:top_n]], [e for e in self.hf.errors][:5]


def to_choice(mode_key, c):
    files = [{"path": p, "sha256": s, "size": None} for p, s in zip(c.files["files"], c.files["sha"])]
    total = c.files["size"]
    if len(files) == 1:
        files[0]["size"] = total
    mm = None
    if c.mmproj:
        mm = {"path": c.mmproj["path"], "sha256": c.mmproj.get("sha"), "size": c.mmproj.get("size")}
    return {
        "mode": mode_key, "repo": c.id, "url": c.url(), "name": c.name, "quant": c.quant, "bpw": round(c.bpw or 0, 2),
        "params_b": c.size_b, "active_b": c.active_b, "arch": c.arch, "ctx": c.ctx, "files": files,
        "size": total, "mmproj": mm, "download_gib": round(gib(total + ((mm or {}).get("size") or 0)), 2),
        "fit": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.fit.items()},
        "n_cpu_moe": c.fit.get("n_cpu_moe", 0), "reasons": c.reasons, "warnings": c.warnings,
        "score": c.score, "uncensored": bool(c.evidence), "thinking": bool(re.search(r"think|reason|r1|qwq", c.id.lower())),
    }


def fill_sizes(hf, choice):
    """Per-file sizes for split GGUFs (needed for verified downloads)."""
    files = [f for f in (choice.get("files") or []) if isinstance(f, dict)]
    if all(f.get("size") for f in files):
        return choice
    sizes = {}
    for t in hf.tree(choice["repo"]):
        lfs = t.get("lfs") if isinstance(t.get("lfs"), dict) else {}
        sizes[t.get("path")] = t.get("size") or lfs.get("size")
    for f in files:
        f["size"] = sizes.get(f.get("path")) or f.get("size")
    return choice


def describe_choice(i, ch):
    lines = ["  %d) %s   [%s, %s GiB download]" % (i, ch["repo"], ch["quant"], ch["download_gib"]),
             "     %s%s, %s context" % (("%gB" % ch["params_b"]) if ch["params_b"] else "?",
                                       (" (MoE, %gB active)" % ch["active_b"]) if ch["active_b"] else "", ch["ctx"])]
    for r in ch["reasons"][:4]:
        lines.append("     + " + r)
    for w in ch["warnings"][:3]:
        lines.append("     ! " + w)
    lines.append("     " + ch["url"])
    return "\n".join(lines)
