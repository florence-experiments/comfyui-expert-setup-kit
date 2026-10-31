"""Shared HTTP session with sane timeouts, proxy and size caps."""
from __future__ import annotations

import requests
from urllib.parse import urlsplit

from ..config import load_config

_SESSION: requests.Session | None = None


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class _Session(requests.Session):
    """requests.Session that never sends this computer's own services (ComfyUI, llama-server) through a proxy,
    neither the one set in config.yaml nor HTTP(S)_PROXY from the environment."""

    def request(self, method, url, *args, **kwargs):
        try:
            host = (urlsplit(str(url)).hostname or "").lower()
        except ValueError:
            host = ""
        if host in _LOCAL_HOSTS:
            kwargs["proxies"] = {"http": None, "https": None}
        return super().request(method, url, *args, **kwargs)


def session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        cfg = load_config()
        s = _Session()
        s.headers["User-Agent"] = cfg["network"].get("user_agent") or "ComfyUI-Expert/1.0"
        proxy = (cfg["network"].get("proxy") or "").strip()
        if proxy:
            s.proxies = {"http": proxy, "https": proxy}
        _SESSION = s
    return _SESSION


def get_json(url: str, params: dict | None = None, headers: dict | None = None, timeout: int = 30):
    r = session().get(url, params=params, headers=headers or {}, timeout=timeout)
    ctype = r.headers.get("content-type", "")
    data = None
    if "json" in ctype or r.text[:1] in "[{":
        try:
            data = r.json()
        except ValueError:
            data = None
    return r.status_code, data, r


def read_capped(r: requests.Response, max_bytes: int) -> bytes:
    buf = bytearray()
    for chunk in r.iter_content(65536):
        buf.extend(chunk)
        if len(buf) >= max_bytes:
            break
    return bytes(buf[:max_bytes])


def human_size(n: float | int | None) -> str:
    if n is None:
        return "?"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"
