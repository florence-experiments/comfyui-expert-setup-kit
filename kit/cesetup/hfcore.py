"""Hugging Face search, GGUF header, KV-cache and download helpers.

Same logic as the HomeAI Setup Kit: GGUF-only file picking, quant parsing, GGUF metadata from the first
megabytes of a file (HTTP range request), KV-cache estimate, model-card refusal statistics, resumable SHA-256
verified downloads. Standard library only; contacts only https://huggingface.co and its CDN (*.hf.co).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .util import GiB, gib, say

UA = "ComfyUI-Expert-Setup-Kit/1.0 (+stdlib urllib)"

# ------------------------------------------------------------------------------------------------ name parsing
QUANT_BPW = {  # approximate bits per weight, used for ordering / closest match
    "IQ1_S": 1.56, "IQ1_M": 1.75, "TQ1_0": 1.69, "TQ2_0": 2.06, "Q2_0": 2.1, "IQ2_XXS": 2.06, "IQ2_XS": 2.31,
    "IQ2_S": 2.5, "IQ2_M": 2.7, "Q2_K_S": 2.79, "Q2_K": 2.96, "Q3_K": 3.74, "Q4_K": 4.89, "Q5_K": 5.69, "Q2_K_P": 3.1, "Q2_K_L": 3.2, "IQ3_XXS": 3.06,
    "IQ3_XS": 3.3, "IQ3_S": 3.44, "IQ3_M": 3.66, "Q3_K_S": 3.41, "Q3_K_M": 3.74, "Q3_K_P": 3.9, "Q3_K_L": 4.03,
    "Q3_K_XL": 4.1, "IQ4_XS": 4.25, "IQ4_NL": 4.5, "Q4_0": 4.55, "Q4_K_S": 4.58, "Q4_1": 5.0, "Q4_K_M": 4.89,
    "Q4_K_L": 5.0, "Q4_K_XL": 5.0, "Q4_K_P": 5.2, "MXFP4": 4.25, "Q5_0": 5.54, "Q5_K_S": 5.54, "Q5_1": 6.0,
    "Q5_K_M": 5.69, "Q5_K_L": 5.8, "Q5_K_XL": 5.9, "Q5_K_P": 5.95, "Q6_K": 6.56, "Q6_K_L": 6.7, "Q6_K_XL": 6.8,
    "Q6_K_P": 7.0, "Q8_0": 8.5, "Q8_K_XL": 9.0, "Q8_K_P": 9.0, "F16": 16.0, "BF16": 16.0, "F32": 32.0,
}
QUANT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:UD-)?(IQ[1-4]_(?:XXS|XS|S|M|NL)|TQ[12]_0|Q[2-8]_K(?:_(?:XXL|XL|L|M|S|P))?|Q[2-8]_[01]|"
    r"MXFP4(?:_MOE)?|BF16|F16|F32|Q2_0)(?![A-Za-z0-9])", re.I)
SPLIT_RE = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)


def parse_quant(name):
    """Return (quant, imatrix, unsloth_dynamic). Last match wins (the quant sits at the end of a file name)."""
    base = os.path.basename(name)
    ms = list(QUANT_RE.finditer(base.replace(".", "-")))
    if not ms:
        return None, False, False
    q = ms[-1].group(1).upper()
    if q == "MXFP4_MOE":
        q = "MXFP4"
    imat = bool(re.search(r"(^|[.\-_])i1[.\-_]|imatrix|-imat", base, re.I))
    ud = "UD-" in base.upper()
    return q, imat, ud


def bpw(q):
    return QUANT_BPW.get((q or "").upper())


SIZE_RE = re.compile(r"(?<![A-Za-z0-9.])(\d{1,4}(?:\.\d+)?)\s?[Bb](?![A-Za-z0-9])")
ACTIVE_RE = re.compile(r"(?<![A-Za-z0-9])A(\d{1,3}(?:\.\d+)?)B(?![A-Za-z0-9])", re.I)


def parse_size(name):
    """Total and active (MoE) parameter count in billions from a name like 'Qwen3.6-35B-A3B'."""
    s = name.replace("_", "-")
    act = ACTIVE_RE.search(s)
    total = None
    for m in SIZE_RE.finditer(s):
        if act and m.start() == act.start() + 1:
            continue
        total = float(m.group(1))
        break
    return total, (float(act.group(1)) if act else None)


def vtuple(v):
    if v is None:
        return None
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return None


def vstr(t):
    return ".".join(str(x) for x in t) if t else "?"


def norm_id(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def strip_repo_suffix(repo_name):
    n = re.sub(r"(?i)[-_.](i1-)?gguf$", "", repo_name)
    n = re.sub(r"(?i)[-_.]i1$", "", n)
    return n



# ------------------------------------------------------------------------------------------------ HTTP
def check_url(url, allowed):
    p = urllib.parse.urlsplit(url)
    host = (p.hostname or "").lower()
    if p.scheme != "https" or not any(host == a or host.endswith("." + a) for a in allowed):
        raise PermissionError("refused to contact %s (only https to %s is allowed)" % (host or url, ", ".join(allowed)))
    return host


class HostGuard(urllib.request.HTTPRedirectHandler):
    """Every redirect hop must be https to an allowed host. The HF token is an unredirected header,
    so it is never forwarded to the CDN."""

    def __init__(self, allowed):
        super().__init__()
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.allowed)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HF:
    API = "https://huggingface.co"
    EXPAND = ["downloads", "likes", "lastModified", "createdAt", "tags", "cardData", "gguf", "author"]

    def __init__(self, cfg, use_cache=True):
        self.cfg = cfg
        self.allowed = [a.lower() for a in cfg["allowed_hosts"]]
        self.opener = urllib.request.build_opener(HostGuard(self.allowed))
        self.token = cfg.get("token") or None   # only a token the user typed in; never read from disk or env
        self.cache_dir = cfg["cache_dir"] if use_cache else None
        self.cache_s = float(cfg.get("cache_hours", 6)) * 3600
        self.calls = 0
        self.errors = []
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)

    def _req(self, url, headers=None):
        host = check_url(url, self.allowed)
        r = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        if self.token and host == "huggingface.co":
            r.add_unredirected_header("Authorization", "Bearer " + self.token)
        return r

    def open(self, url, headers=None, timeout=60):
        return self.opener.open(self._req(url, headers), timeout=timeout)

    def _cache_path(self, url, prefix=""):
        return os.path.join(self.cache_dir, prefix + hashlib.sha1(url.encode()).hexdigest() + ".json")

    def _cached(self, url, prefix=""):
        if not self.cache_dir:
            return None, None
        cp = self._cache_path(url, prefix)
        if os.path.exists(cp) and time.time() - os.path.getmtime(cp) < self.cache_s:
            with open(cp, encoding="utf-8") as f:
                return cp, json.load(f)
        return cp, None

    @staticmethod
    def _store(cp, data):
        if cp and data is not None:
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(data, f)

    def get_json(self, path, params=None):
        url = self.API + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True, safe="[]")
        cp, hit = self._cached(url)
        if hit is not None:
            return hit
        for attempt in range(4):
            try:
                self.calls += 1
                with self.open(url, {"Accept": "application/json"}) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                self._store(cp, data)
                return data
            except urllib.error.HTTPError as ex:
                if ex.code == 429 or ex.code >= 500:
                    time.sleep(min(float(ex.headers.get("Retry-After") or (2 + attempt * 4)), 30))
                    continue
                self.errors.append("%s -> HTTP %d" % (path, ex.code))
                return None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as ex:
                if attempt == 3:
                    self.errors.append("%s -> %s" % (path, ex))
                    return None
                time.sleep(2 + attempt * 3)
        self.errors.append("%s -> gave up after retries" % path)
        return None

    def get_text(self, path, limit=400_000):
        url = self.API + path
        cp, hit = self._cached(url, "txt-")
        if hit is not None:
            return hit
        try:
            self.calls += 1
            with self.open(url, timeout=40) as resp:
                txt = resp.read(limit).decode("utf-8", "replace")
        except urllib.error.HTTPError as ex:
            txt = "" if ex.code == 404 else None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
            txt = None
        self._store(cp, txt)
        return txt or ""

    def get_range(self, url, start, end):
        try:
            self.calls += 1
            with self.open(url, {"Range": "bytes=%d-%d" % (start, end)}, timeout=60) as resp:
                return resp.read(end - start + 1)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as ex:
            self.errors.append("header of %s -> %s" % (url.rsplit("/", 1)[-1], ex))
            return b""

    # ---- API helpers
    def search(self, term, sort="lastModified", limit=50):
        params = [("search", term), ("filter", "gguf"), ("sort", sort), ("direction", "-1"), ("limit", str(limit))]
        params += [("expand[]", x) for x in self.EXPAND]
        return self.get_json("/api/models", params) or []

    def model(self, repo):
        return self.get_json("/api/models/" + repo, [("expand[]", x) for x in self.EXPAND])

    def tree(self, repo):
        d = self.get_json("/api/models/%s/tree/main" % repo, {"recursive": "true"})
        return d if isinstance(d, list) else []

    def readme(self, repo):
        return self.get_text("/%s/raw/main/README.md" % repo)

    def file_url(self, repo, path):
        return "%s/%s/resolve/main/%s" % (self.API, repo, urllib.parse.quote(path))




# ------------------------------------------------------------------------------------------------ GGUF header
GGUF_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


class _Trunc(Exception):
    pass


def parse_gguf_header(buf):
    """Parse GGUF metadata from the first bytes of a file; stops quietly when the buffer runs out.
    Big arrays (tokenizer vocab) are skipped, small numeric arrays (per-layer values) are kept."""
    out = {}
    if len(buf) < 24 or buf[:4] != b"GGUF":
        return out
    pos = 4
    ver, = struct.unpack_from("<I", buf, pos); pos += 4
    if ver < 2:
        return out
    n_tensors, n_kv = struct.unpack_from("<QQ", buf, pos); pos += 16
    out["_n_tensors"] = n_tensors

    def need(n):
        if pos + n > len(buf):
            raise _Trunc()

    def rd_str():
        nonlocal pos
        need(8)
        ln, = struct.unpack_from("<Q", buf, pos); pos += 8
        need(ln)
        s = buf[pos:pos + ln]; pos += ln
        return s.decode("utf-8", "replace")

    def rd_val(t, keep=True):
        nonlocal pos
        if t in GGUF_SCALAR:
            fmt = GGUF_SCALAR[t]; sz = struct.calcsize(fmt)
            need(sz)
            v, = struct.unpack_from(fmt, buf, pos); pos += sz
            return v
        if t == 8:
            return rd_str()
        if t == 9:
            need(12)
            et, cnt = struct.unpack_from("<IQ", buf, pos); pos += 12
            if et in GGUF_SCALAR:
                sz = struct.calcsize(GGUF_SCALAR[et])
                need(sz * cnt)
                vals = (list(struct.unpack_from("<%d%s" % (cnt, GGUF_SCALAR[et][1]), buf, pos))
                        if keep and cnt <= 512 else "<array %d>" % cnt)
                pos += sz * cnt
                return vals
            vals = []
            for _ in range(cnt):
                v = rd_val(et, keep=False)
                if keep and len(vals) < 16:
                    vals.append(v)
            return vals if cnt <= 16 else "<array %d>" % cnt
        raise _Trunc()

    try:
        for _ in range(n_kv):
            k = rd_str()
            need(4)
            t, = struct.unpack_from("<I", buf, pos); pos += 4
            v = rd_val(t, keep=not k.startswith("tokenizer.ggml."))
            if k.startswith("tokenizer.chat_template"):
                v = "<template>"
            out[k] = v
    except (_Trunc, struct.error):
        out["_truncated"] = True
    return out


KV_BYTES = {"f32": 4.0, "f16": 2.0, "bf16": 2.0, "q8_0": 34 / 32, "q5_1": 24 / 32, "q5_0": 22 / 32,
            "q4_1": 20 / 32, "q4_0": 18 / 32, "iq4_nl": 18 / 32}


def arch_info(meta):
    """The numbers a KV-cache estimate needs, from parsed GGUF metadata."""
    a = (meta or {}).get("general.architecture")
    if not a:
        return None

    def g(k):
        return meta.get("%s.%s" % (a, k))

    return {
        "arch": a, "n_layer": g("block_count"), "n_embd": g("embedding_length"), "n_head": g("attention.head_count"),
        "n_head_kv": g("attention.head_count_kv"), "k_len": g("attention.key_length"),
        "v_len": g("attention.value_length"), "ctx_train": g("context_length"),
        "swa": g("attention.sliding_window"), "swa_pattern": g("attention.sliding_window_pattern"),
        "full_attn_interval": g("full_attention_interval"), "experts": g("expert_count"),
        "experts_used": g("expert_used_count"), "kv_lora_rank": g("attention.kv_lora_rank"),
        "nextn": g("nextn_predict_layers"), "ssm": g("ssm.state_size"),
        "name": meta.get("general.name"), "size_label": meta.get("general.size_label"),
    }


def kv_estimate(info, ctx, cache_k="f16", cache_v="f16", params_b=None):
    """KV cache bytes for `ctx` tokens -> (bytes, note). Handles GQA, per-layer kv-head arrays, hybrid
    DeltaNet/SSM models (only every Nth layer keeps KV) and sliding-window layers (cache capped at the window)."""
    bk = KV_BYTES.get((cache_k or "f16").lower(), 2.0)
    bv = KV_BYTES.get((cache_v or "f16").lower(), 2.0)
    if not info or not info.get("n_layer"):
        p = params_b or 20     # ~6.8 KiB of f16 KV per token per billion params (Mistral-24B-like GQA)
        per_tok = 6.8 * 1024 * p * (bk + bv) / 4.0
        return int(per_tok * ctx), "rough estimate (GGUF header not read): ~%.0f KiB/token" % (per_tok / 1024)
    n_layer = int(info["n_layer"])
    try:
        if info.get("nextn"):
            n_layer = max(1, n_layer - int(info["nextn"]))
    except (TypeError, ValueError):
        pass
    n_head = info.get("n_head") or 32
    if isinstance(n_head, list):
        n_head = max(n_head) or 32
    emb = info.get("n_embd") or 4096
    k_len = info.get("k_len") or (emb // n_head)
    v_len = info.get("v_len") or k_len
    hkv = info.get("n_head_kv")
    per_layer = [int(x) for x in hkv[:n_layer]] if isinstance(hkv, list) else [int(hkv or n_head)] * n_layer
    notes = []
    if info.get("kv_lora_rank"):            # MLA (DeepSeek-style): compressed latent per layer
        per = (int(info["kv_lora_rank"]) + 64) * bk
        return int(per * n_layer * ctx), "MLA latent cache"
    fai = info.get("full_attn_interval")
    if fai and not isinstance(hkv, list):
        try:
            fai = int(fai)
            per_layer = [h if (i + 1) % fai == 0 else 0 for i, h in enumerate(per_layer)]
        except (TypeError, ValueError):
            fai = None
    if any(h == 0 for h in per_layer):
        notes.append("hybrid: %d of %d layers keep KV" % (sum(1 for h in per_layer if h), n_layer))
    swa = info.get("swa")
    swa_layers = set()
    if swa:
        pat = info.get("swa_pattern")
        if isinstance(pat, list):
            swa_layers = {i for i, v in enumerate(pat[:n_layer]) if v}
        else:
            try:
                p = int(pat) if pat else 6          # gemma default: 5 local : 1 global
            except (TypeError, ValueError):
                p = 6
            swa_layers = {i for i in range(n_layer) if p > 1 and (i + 1) % p != 0}
        notes.append("sliding window %s on %d layers" % (swa, len(swa_layers)))
    total = 0.0
    for i, h in enumerate(per_layer):
        if h:
            t = min(ctx, int(swa) + 512) if (swa and i in swa_layers) else ctx
            total += h * (k_len * bk + v_len * bv) * t
    if info.get("ssm") or fai:
        total += 0.15 * GiB
        notes.append("+0.15 GiB recurrent state")
    return int(total), "; ".join(notes) or "%d layers x %s KV heads x %d dims" % (n_layer, per_layer[0], k_len)



# ------------------------------------------------------------------------------------------------ card parsing
def card_stats(text):
    """Refusal counts, UGI and KL numbers stated in a model card. Untrusted text: only numbers are read."""
    s = {}
    if not text:
        return s
    t = text.replace("**", "").replace("__", "")
    best = None
    for line in re.findall(r"(?im)^.*refus.*$", t):
        for a, b in re.findall(r"(?<![\d.])(\d{1,4})\s*/\s*(\d{2,4})(?![\d.])", line):
            a, b = int(a), int(b)
            if 20 <= b <= 5000 and a <= b:
                best = (a, b); break
        if best:
            break
    if best:
        s["refusals"] = best
        s["refusal_rate"] = best[0] / best[1]
    m = re.search(r"(?i)\bUGI\b(?:[ \t:|=]|score|-)*?(\d{1,3}(?:\.\d+)?)\b", t)
    if m and float(m.group(1)) <= 100:
        s["ugi"] = float(m.group(1))
    m = re.search(r"(?i)\bKL[ -]?(?:div(?:ergence)?)?\b[^\n\d]{0,30}(\d+\.\d+)", t)
    if m:
        s["kl"] = float(m.group(1))
    m = re.search(r"(?i)llama\.cpp[^\n]{0,40}?\b(?:b|build\s*)(\d{4,5})\b[^\n]{0,15}(?:or newer|or later|\+|and up)", t)
    if m:
        s["llamacpp_min"] = int(m.group(1))
    if re.search(r"(?i)(requires? (?:a |our |the )?(?:custom|patched|forked) llama\.cpp|"
                 r"not (?:yet )?supported (?:in|by) (?:mainline |upstream )?llama\.cpp|"
                 r"llama\.cpp (?:fork|PR #?\d+) (?:is )?required)", t):
        s["needs_fork_hint"] = True
    return s


def days_since(iso):
    if not iso:
        return None
    try:
        d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (dt.datetime.now(dt.timezone.utc) - d).total_seconds() / 86400
    except ValueError:
        return None



class Cand:
    def __init__(self, info):
        self.id = info.get("id") or info.get("modelId")
        self.author = self.id.split("/")[0]
        self.name = self.id.split("/", 1)[-1]
        self.info = info
        self.downloads = info.get("downloads") or 0
        self.likes = info.get("likes") or 0
        self.modified = info.get("lastModified")
        self.created = info.get("createdAt")
        self.tags = [t.lower() for t in (info.get("tags") or []) if isinstance(t, str)]
        card = info.get("cardData") or {}
        bm = card.get("base_model") or []
        self.base_models = [bm] if isinstance(bm, str) else [b for b in bm if isinstance(b, str)]
        gg = info.get("gguf") or {}
        self.api_arch = gg.get("architecture")
        self.api_params = gg.get("total")
        self.api_ctx = gg.get("context_length")
        self.size_b, self.active_b = parse_size(self.name)
        if self.api_params and not self.size_b:
            self.size_b = round(self.api_params / 1e9, 1)
        # origin model = what was quantized; collapses bartowski/mradermacher/... builds of one model
        origin = next((b for b in self.base_models if "gguf" not in b.lower()), None)
        self.origin = origin or strip_repo_suffix(self.name)
        self.origin_key = norm_id(self.origin.split("/")[-1])
        self.relation = None
        self.version = None
        self.base_version = None
        self.evidence = []
        self.score = 0.0
        self.reasons = []
        self.warnings = []
        self.files = None
        self.quant = None
        self.file_list = []
        self.size = None
        self.mmproj = None
        self.mmproj_size = None
        self.fit = None
        self.header = None
        self.arch = self.api_arch
        self.stats = {}
        self.also = []
        self.mtp = False
        self.ok = True

    def hay(self):
        return (self.id + " " + " ".join(self.base_models) + " " + " ".join(self.tags)).lower()

    def url(self):
        return "https://huggingface.co/" + self.id


def uncensored_evidence(c, cfg):
    hay = c.hay()
    strong = [k for k in cfg["uncensored_keywords"] if k.lower() not in cfg["weak_keywords"] and k.lower() in hay]
    weak = [k for k in cfg["weak_keywords"] if k.lower() in hay]
    return strong, weak


def pick_files(tree, params_b=None):
    """GGUF quants in a repo -> {label: {'files': [...], 'size': n, 'sha': [...], 'bpw': x}} plus mmproj options.
    Files without a standard quant name (e.g. '...-21G-ICE.gguf', APEX builds) are keyed by their distinctive suffix."""
    quants, mmprojs, odd = {}, [], []
    for f in tree:
        if f.get("type") != "file":
            continue
        p = f.get("path", "")
        low = p.lower()
        if not low.endswith(".gguf"):
            continue
        size = f.get("size") or (f.get("lfs") or {}).get("size") or 0
        sha = (f.get("lfs") or {}).get("oid") or (f.get("lfs") or {}).get("sha256")
        if "mmproj" in low:
            mmprojs.append({"path": p, "size": size, "sha": sha})
            continue
        base = low.rsplit("/", 1)[-1]
        if any(x in low for x in ("imatrix", "fastmtp", "-draft", "eagle", "dflash")) or base.startswith(("mtp-", "draft-")):
            continue
        q, imat, ud = parse_quant(p)
        if not q:
            odd.append((p, size, sha))
            continue
        key = ("UD-" if ud else "") + q + (" (i1)" if imat and "i1" in low else "")
        e = quants.setdefault(key, {"quant": q, "files": [], "size": 0, "sha": [], "imatrix": imat, "ud": ud})
        e["files"].append(p)
        e["sha"].append(sha)
        e["size"] += size
    if odd:
        names = [os.path.basename(SPLIT_RE.sub(".gguf", p))[:-5] for p, _, _ in odd]
        pre = os.path.commonprefix(names) if len(names) > 1 else ""
        pre = pre[: pre.rfind("-") + 1] if "-" in pre else ""
        for (p, size, sha), n in zip(odd, names):
            key = n[len(pre):] or n
            e = quants.setdefault(key, {"quant": key, "files": [], "size": 0, "sha": [], "imatrix": False, "ud": False})
            e["files"].append(p); e["sha"].append(sha); e["size"] += size
    for e in quants.values():
        e["bpw"] = bpw(e["quant"]) or ((e["size"] * 8 / (params_b * 1e9)) if params_b else 0)
        e["files_sha"] = sorted(zip(e["files"], e["sha"]))
        e["files"] = [x for x, _ in e["files_sha"]]
        e["sha"] = [y for _, y in e["files_sha"]]
    return quants, mmprojs


def pick_mmproj(mmprojs):
    if not mmprojs:
        return None
    pref = ["bf16", "f16", "q8_0", "f32"]

    def rank(m):
        low = m["path"].lower()
        return next((i for i, k in enumerate(pref) if k in low), 9)

    return sorted(mmprojs, key=rank)[0]



def sha256_file(path, start_hash=None):
    h = start_hash or hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(8 * 1024 * 1024)
            if not b:
                break
            h.update(b)
    return h


def download_file(hf, repo, path, dest_dir, expected_size, expected_sha):
    """Resumable download into dest_dir. Never overwrites: an existing complete file is verified and kept."""
    os.makedirs(dest_dir, exist_ok=True)
    name = path.rsplit("/", 1)[-1]
    final = os.path.join(dest_dir, name)
    part = final + ".part"
    if os.path.exists(final):
        say("   %s already exists - checking it instead of downloading" % name)
        ok = os.path.getsize(final) == expected_size and (not expected_sha or sha256_file(final).hexdigest() == expected_sha)
        say("   %s" % ("verified OK" if ok else "EXISTING FILE DOES NOT MATCH - left untouched, nothing downloaded"))
        return ok, final
    free = shutil.disk_usage(dest_dir).free
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if expected_size and free < (expected_size - have) + 2 * GiB:
        say("   not enough free space on %s (%.1f GiB free, need %.1f)" % (dest_dir, gib(free), gib(expected_size - have) + 2))
        return False, None
    h = hashlib.sha256()
    if have:
        if expected_size and have > expected_size:
            os.replace(part, part + ".oversize")
            have = 0
        else:
            say("   resuming at %.2f GiB (re-hashing the part already on disk)" % gib(have))
            h = sha256_file(part)
    url = hf.file_url(repo, path)
    t0, last = time.time(), 0.0
    for attempt in range(6):
        try:
            hdr = {"Range": "bytes=%d-" % have} if have else {}
            with hf.open(url, hdr, timeout=60) as resp:
                if have and resp.status != 206:
                    say("   server ignored resume; starting over")
                    have, h = 0, hashlib.sha256()
                    mode = "wb"
                else:
                    mode = "ab" if have else "wb"
                with open(part, mode) as out:
                    while True:
                        b = resp.read(4 * 1024 * 1024)
                        if not b:
                            break
                        out.write(b)
                        h.update(b)
                        have += len(b)
                        if time.time() - last > 2:
                            last = time.time()
                            rate = have / max(1, last - t0)
                            pct = 100 * have / expected_size if expected_size else 0
                            sys.stdout.write("\r   %s  %5.1f%%  %.2f / %.2f GiB  %.1f MB/s   " % (
                                name[:40], pct, gib(have), gib(expected_size), rate / 1e6))
                            sys.stdout.flush()
            break
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as ex:
            say("\n   connection problem (%s), retrying in %ds..." % (ex, 5 * (attempt + 1)))
            time.sleep(5 * (attempt + 1))
            have = os.path.getsize(part) if os.path.exists(part) else 0
            h = sha256_file(part) if have else hashlib.sha256()
    say("")
    if expected_size and have != expected_size:
        say("   incomplete (%d of %d bytes). Run again to resume." % (have, expected_size))
        return False, None
    got = h.hexdigest()
    if expected_sha and got != expected_sha:
        os.replace(part, final + ".bad-sha")
        say("   SHA-256 MISMATCH - kept as %s.bad-sha for inspection, NOT used." % name)
        return False, None
    os.replace(part, final)
    say("   done, SHA-256 verified" if expected_sha else "   done (no SHA-256 published for this file)")
    return True, final

