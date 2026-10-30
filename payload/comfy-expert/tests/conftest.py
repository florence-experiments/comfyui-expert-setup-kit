import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def offline_cfg(tmp_path, monkeypatch):
    """Isolated config: ComfyUI 'not running' (port 9), temp model + workflow folders."""
    import yaml
    from comfy_expert import config
    from comfy_expert.tools import comfy, net
    models = tmp_path / "models"
    (models / "checkpoints").mkdir(parents=True)
    (models / "loras").mkdir()
    (models / "checkpoints" / "juggernautXL_ragnarok.safetensors").write_bytes(b"x")
    wfd = tmp_path / "workflows"
    wfd.mkdir()
    (wfd / "anime_portrait.json").write_text((FIX / "anime_portrait.json").read_text())
    cfgf = tmp_path / "config.yaml"
    cfgf.write_text(yaml.safe_dump({
        "llm": {"base_url": "http://127.0.0.1:9/v1", "model": "test-model", "stream": False},
        "comfyui": {"url": "http://127.0.0.1:9", "root": "", "model_roots": [str(models)],
                    "workflow_dirs": [str(wfd)], "download_root": str(models)}}))
    monkeypatch.setenv("COMFY_EXPERT_CONFIG", str(cfgf))
    from comfy_expert.tools import workflow as _wfmod
    monkeypatch.setattr(_wfmod, "DRAFTS_DIR", tmp_path / "drafts")
    config.load_config(cfgf, reload=True)
    net._SESSION = None
    comfy._OI_CACHE.update(t=0, data=None, source=None)
    from comfy_expert.tools import load_all
    load_all()
    yield {"models": models, "workflows": wfd, "tmp": tmp_path}


@pytest.fixture
def anime_wf():
    return json.loads((FIX / "anime_portrait.json").read_text())
