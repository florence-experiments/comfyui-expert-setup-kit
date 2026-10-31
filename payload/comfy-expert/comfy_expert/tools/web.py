"""Web search, page fetch, GitHub search and custom-node pack lookup."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup

from . import tool, ToolError
from .net import session, read_capped, get_json
from ..config import load_config, APP_DIR

CACHE_DIR = APP_DIR / "cache"


def _searx(query: str, n: int) -> list[dict]:
    url = load_config()["search"]["searxng_url"].rstrip("/")
    code, data, _ = get_json(f"{url}/search", params={"q": query, "format": "json"})
    if code != 200 or not data:
        raise ToolError(f"SearXNG returned HTTP {code}")
    return [{"title": r.get("title"), "url": r.get("url"), "snippet": (r.get("content") or "")[:300]}
            for r in data.get("results", [])[:n]]


def _ddg(query: str, n: int) -> list[dict]:
    cfg = load_config()
    try:
        from ddgs import DDGS  # new package name
    except ImportError:  # pragma: no cover
        from duckduckgo_search import DDGS  # type: ignore
    proxy = cfg["network"].get("proxy") or None
    last = None
    for attempt in range(2):
        try:
            with DDGS(proxy=proxy) as d:
                res = d.text(query, region=cfg["search"].get("region", "wt-wt"),
                             safesearch=cfg["search"].get("safesearch", "off"), max_results=n)
            return [{"title": r.get("title"), "url": r.get("href") or r.get("url"), "snippet": (r.get("body") or "")[:300]}
                    for r in (res or [])]
        except Exception as e:  # rate limit etc.
            last = e
            time.sleep(1.5)
    raise ToolError(f"Web search failed: {last}")


@tool("web_search",
      "Search the web (DuckDuckGo, or SearXNG if configured). Use for anything you are not sure about: node packs, "
      "model pages on Tensor.Art / SeaArt / Civitai / Hugging Face, guides, error messages. Add 'site:civitai.com' etc. to focus.",
      {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 8}}, ["query"], category="web")
def web_search(query: str, max_results: int = 8):
    n = max(1, min(int(max_results or 8), 20))
    if load_config()["search"].get("searxng_url"):
        try:
            return {"results": _searx(query, n), "backend": "searxng"}
        except Exception:
            pass
    return {"results": _ddg(query, n), "backend": "duckduckgo"}


def html_to_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    for t in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "form", "iframe"]):
        t.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    lines = []
    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "code", "td", "th", "a"]):
        if el.name == "a":
            href = el.get("href") or ""
            txt = el.get_text(" ", strip=True)
            if href.startswith("http") and txt and len(txt) < 120 and el.parent and el.parent.name not in ("p", "li"):
                lines.append(f"[{txt}]({href})")
            continue
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            txt = "#" * int(el.name[1]) + " " + txt
        elif el.name == "li":
            txt = "- " + txt
        lines.append(txt)
    out, seen = [], set()
    for l in lines:
        if l not in seen:
            seen.add(l)
            out.append(l)
    text = "\n".join(out)
    if len(text) < 200:
        text = main.get_text("\n", strip=True)
    return title, re.sub(r"\n{3,}", "\n\n", text)


@tool("fetch_url",
      "Download a web page or JSON/text file and return readable text (size-capped). Use offset to read further. "
      "GitHub repo URLs return the README. Use it to verify model pages, node pack READMEs, docs.",
      {"url": {"type": "string"}, "offset": {"type": "integer", "default": 0},
       "max_chars": {"type": "integer", "default": 8000}}, ["url"], category="web")
def fetch_url(url: str, offset: int = 0, max_chars: int = 8000):
    if not re.match(r"^https?://", url or ""):
        raise ToolError("url must start with http:// or https://")
    m = re.match(r"^https?://github\.com/([^/]+)/([^/#?]+)/?$", url)
    if m:  # repo root -> README via API (clean markdown)
        r = session().get(f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/readme",
                          headers={"Accept": "application/vnd.github.raw", **_gh_headers()}, timeout=30)
        if r.status_code == 200:
            text = r.text
            return _page(url, f"{m.group(1)}/{m.group(2)} README", text, offset, max_chars, 200)
    r = session().get(url, timeout=30, stream=True, allow_redirects=True)
    raw = read_capped(r, 3_000_000)
    ctype = r.headers.get("content-type", "")
    if r.status_code >= 400:
        snippet = raw[:400].decode("utf-8", "replace")
        raise ToolError(f"HTTP {r.status_code} for {url}: {snippet}")
    if any(b in ctype for b in ("image/", "video/", "octet-stream", "zip")):
        return {"url": r.url, "status": r.status_code, "content_type": ctype,
                "size_header": r.headers.get("content-length"), "text": "(binary file, not shown)"}
    text = raw.decode(r.encoding or "utf-8", "replace")
    title = ""
    if "json" in ctype:
        try:
            text = json.dumps(json.loads(text), indent=1)[:200000]
        except ValueError:
            pass
    elif "html" in ctype or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        title, text = html_to_text(text)
    return _page(r.url, title, text, offset, max_chars, r.status_code)


def _page(url, title, text, offset, max_chars, status):
    max_chars = max(500, min(int(max_chars or 8000), 20000))
    offset = max(0, int(offset or 0))
    chunk = text[offset: offset + max_chars]
    res = {"url": url, "status": status, "title": title, "total_chars": len(text), "offset": offset, "text": chunk}
    if offset + max_chars < len(text):
        res["next_offset"] = offset + max_chars
    return res


def _gh_headers() -> dict:
    tok = load_config().key("github_token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


@tool("github_search",
      "Search GitHub repositories (e.g. ComfyUI custom node packs). 'comfyui' is added to the query unless present.",
      {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 8}}, ["query"], category="web")
def github_search(query: str, max_results: int = 8):
    q = query if "comfy" in query.lower() else f"{query} comfyui"
    code, data, _ = get_json("https://api.github.com/search/repositories",
                             params={"q": q, "sort": "stars", "order": "desc", "per_page": min(int(max_results or 8), 30)},
                             headers={"Accept": "application/vnd.github+json", **_gh_headers()})
    if code != 200 or not data:
        if code in (403, 429):  # rate limited (10/min without token) -> web search fallback
            try:
                res = _ddg(f"site:github.com {q}", min(int(max_results or 8), 10))
                return {"source": "web search fallback (GitHub API rate-limited; set GITHUB_TOKEN to avoid)",
                        "results": [r for r in res if "github.com/" in (r.get("url") or "")]}
            except Exception:
                pass
        raise ToolError(f"GitHub search failed (HTTP {code}). Without GITHUB_TOKEN the limit is 10 searches/minute.")
    return {"total": data.get("total_count"), "results": [
        {"repo": i["full_name"], "url": i["html_url"], "stars": i["stargazers_count"],
         "description": (i.get("description") or "")[:200], "updated": i.get("pushed_at"), "archived": i.get("archived")}
        for i in data.get("items", [])]}


NODE_MAP_URL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/extension-node-map.json"


def _node_map() -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / "extension-node-map.json"
    cached = None
    if f.exists():
        try:
            cached = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = None
        if not isinstance(cached, dict):       # damaged cache = a miss (it is fetched again below)
            cached = None
    if cached is None or time.time() - f.stat().st_mtime > 3 * 86400:
        try:
            r = session().get(NODE_MAP_URL, timeout=60)
            fresh = r.json() if r.status_code == 200 else None
            if isinstance(fresh, dict) and fresh:
                tmp = f.with_name(f".{f.name}.{os.getpid()}.tmp")
                tmp.write_text(json.dumps(fresh), encoding="utf-8")
                os.replace(tmp, f)
                return fresh
        except Exception:
            if cached is None:
                raise ToolError("Could not download ComfyUI-Manager's node map (no usable copy in the cache)")
        if cached is None:
            raise ToolError("ComfyUI-Manager's node map could not be read (no usable copy in the cache)")
    return cached


@tool("find_node_pack",
      "Find which custom node pack (GitHub repo) provides a node class, using ComfyUI-Manager's official node map. "
      "Use for red / missing nodes. Returns repo URLs to install via ComfyUI-Manager.",
      {"node_type": {"type": "string", "description": "Exact node class/type, e.g. 'FaceDetailer'"}}, ["node_type"], category="web")
def find_node_pack(node_type: str):
    data = _node_map()
    exact, fuzzy = [], []
    low = node_type.lower()
    for repo, val in data.items():
        names = val[0] if isinstance(val, list) and val else []
        meta = val[1] if isinstance(val, list) and len(val) > 1 else {}
        if node_type in names:
            exact.append({"repo": repo, "title": meta.get("title_aux"), "nodes_in_pack": len(names)})
        elif len(fuzzy) < 10 and any(low in n.lower() for n in names):
            fuzzy.append({"repo": repo, "title": meta.get("title_aux"),
                          "matching_nodes": [n for n in names if low in n.lower()][:5]})
        if not exact:
            pat = meta.get("nodename_pattern") if isinstance(meta, dict) else None
            if pat:
                try:
                    if re.search(pat, node_type):
                        exact.append({"repo": repo, "title": meta.get("title_aux"), "matched_by": "name pattern"})
                except re.error:
                    pass
    return {"node_type": node_type, "exact_matches": exact, "similar": fuzzy if not exact else [],
            "how_to_install": "ComfyUI-Manager > Install Custom Nodes (search the title) or 'Install via Git URL' with the repo URL, then restart ComfyUI.",
            "source": NODE_MAP_URL}
