"""Configuration: config.yaml + .env + environment variables (env wins)."""
from __future__ import annotations

import os
import copy
from pathlib import Path
from typing import Any

import yaml

PKG_DIR = Path(__file__).resolve().parent
APP_DIR = PKG_DIR.parent  # folder that holds config.yaml, run.bat, ...

DEFAULTS: dict[str, Any] = {
    "llm": {
        "base_url": "http://127.0.0.1:8080/v1",
        "model": "",            # empty = ask llama-server which model is loaded
        "api_key": "local",
        "temperature": 0.3,
        "max_tokens": 4096,
        "context_size": 32768,  # what you started llama-server with (-c)
        "max_tool_rounds": 30,
        "timeout": 900,
        "max_tool_result_chars": 9000,
        "self_check": True,
    },
    "comfyui": {
        "url": "http://127.0.0.1:8188",
        "root": "",
        "model_roots": [],   # ComfyUI\models is added automatically
        "workflow_dirs": [],  # ComfyUI\user\default\workflows is added automatically
        "generated_subfolder": "generated",
        "download_root": "",
    },
    "vision": {   # Prompt Artist (image -> prompt). '' = use the llm settings above
        "base_url": "", "model": "", "fallback_base_url": "", "fallback_model": "",
        "temperature": 0.6, "max_tokens": 3500, "timeout": 900, "thinking": False, "family_overrides": {},
        "lessons_file": "",   # "" = data\prompt_lessons.json in the app folder
    },
    "search": {"searxng_url": "", "region": "wt-wt", "safesearch": "off"},
    "network": {"proxy": "", "user_agent": "ComfyUI-Expert/1.0", "civitai_fallback_archive": True},
    "ui": {"host": "127.0.0.1", "port": 7860, "open_browser": True},
    "mcp": {"host": "127.0.0.1", "port": 8765},
    "keys": {"civitai_api_key": "", "hf_token": "", "github_token": ""},
    # filled in by the setup kit's system scan, e.g. "Windows, NVIDIA RTX 4070 12 GB VRAM, 32 GB RAM"
    "hardware": {"summary": ""},
}

ENV_MAP = {
    "LLAMA_BASE_URL": ("llm", "base_url"),
    "LLAMA_MODEL": ("llm", "model"),
    "LLAMA_API_KEY": ("llm", "api_key"),
    "LLAMA_CONTEXT": ("llm", "context_size"),
    "COMFYUI_URL": ("comfyui", "url"),
    "COMFYUI_ROOT": ("comfyui", "root"),
    "DOWNLOAD_ROOT": ("comfyui", "download_root"),
    "SEARXNG_URL": ("search", "searxng_url"),
    "HTTPS_PROXY_FOR_TOOLS": ("network", "proxy"),
    "CIVITAI_API_KEY": ("keys", "civitai_api_key"),
    "HF_TOKEN": ("keys", "hf_token"),
    "GITHUB_TOKEN": ("keys", "github_token"),
    "UI_PORT": ("ui", "port"),
    "MCP_PORT": ("mcp", "port"),
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


def load_dotenv(path: Path) -> None:
    """Tiny .env reader (KEY=value lines). Does not override real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


class Config(dict):
    """dict with attribute-free helpers. cfg['llm']['base_url'] etc."""

    @property
    def comfy_root(self) -> Path | None:
        r = self["comfyui"].get("root") or ""
        return Path(r) if r else None

    def model_roots(self) -> list[Path]:
        roots: list[Path] = []
        for r in self["comfyui"].get("model_roots") or []:
            roots.append(Path(r))
        if self.comfy_root:
            roots.append(self.comfy_root / "models")
            roots.extend(extra_model_path_roots(self.comfy_root))
        return _dedupe_paths(roots)

    def workflow_dirs(self) -> list[Path]:
        dirs = [Path(d) for d in (self["comfyui"].get("workflow_dirs") or [])]
        if self.comfy_root:
            dirs.append(self.comfy_root / "user" / "default" / "workflows")
        return _dedupe_paths(dirs)

    def generated_dir(self) -> Path:
        dirs = [d for d in self.workflow_dirs() if d.exists()]
        base = dirs[0] if dirs else APP_DIR / "output"
        return base / (self["comfyui"].get("generated_subfolder") or "generated")

    def download_root(self) -> Path:
        r = self["comfyui"].get("download_root")
        if r:
            return Path(r)
        roots = self.model_roots()
        return roots[0] if roots else APP_DIR / "models"

    def key(self, name: str) -> str:
        return (self["keys"].get(name) or "").strip()


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen, out = set(), []
    for p in paths:
        k = str(p).replace("\\", "/").rstrip("/").lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def extra_model_path_roots(comfy_root: Path) -> list[Path]:
    """Read ComfyUI's extra_model_paths.yaml and return every base folder that holds models.

    Returns the folders that contain model-type subfolders (e.g. <base>/models)."""
    f = comfy_root / "extra_model_paths.yaml"
    if not f.is_file():
        return []
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return []
    roots: list[Path] = []
    if not isinstance(data, dict):
        return []
    for _name, section in data.items():
        if not isinstance(section, dict):
            continue
        base = Path(str(section.get("base_path", "") or "").strip()) if section.get("base_path") else None
        for key, val in section.items():
            if key in ("base_path", "is_default") or not isinstance(val, str):
                continue
            for line in val.splitlines():
                line = line.strip()
                if not line:
                    continue
                p = Path(line)
                if base is not None and not p.is_absolute():
                    p = base / p
                # p is e.g. <base>/models/checkpoints -> root is its parent
                roots.append(p.parent)
    return roots


_CFG: Config | None = None


def load_config(path: str | os.PathLike | None = None, reload: bool = False) -> Config:
    global _CFG
    if _CFG is not None and not reload and path is None:
        return _CFG
    load_dotenv(APP_DIR / ".env")
    cfg_path = Path(path or os.environ.get("COMFY_EXPERT_CONFIG") or APP_DIR / "config.yaml")
    user: dict = {}
    if cfg_path.is_file():
        try:
            user = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, UnicodeDecodeError) as e:
            raise SystemExit(f"{cfg_path} could not be read ({type(e).__name__}: {e}). Fix the file, or run setup again.")
        if not isinstance(user, dict):
            raise SystemExit(f"{cfg_path} must hold settings sections (llm:, comfyui:, ...). Fix the file, or run setup again.")
    cfg = Config(_merge(DEFAULTS, user))
    for env, (sec, key) in ENV_MAP.items():
        v = os.environ.get(env)
        if v:
            cur = cfg[sec].get(key)
            cfg[sec][key] = int(v) if isinstance(cur, int) and v.isdigit() else v
    _CFG = cfg
    return cfg


def set_config(cfg: Config) -> None:
    global _CFG
    _CFG = cfg
