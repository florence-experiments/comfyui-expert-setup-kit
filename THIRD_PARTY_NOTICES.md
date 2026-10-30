# Third-party notices

This repository contains **no executables and no model files**. Programs and models are downloaded at install time
from their official sources, and only after you type yes. Each download is checked against a published SHA-256.
Each program and model keeps its own licence, and you accept that licence when you install it.

## Included in this repository

| Component | Licence |
|---|---|
| The ComfyUI Expert app (`payload/comfy-expert`) and the setup kit (`kit/`) | MIT (see LICENSE) |
| `payload/comfy-expert/comfy_expert/data/object_info_bundled.json`: a list of the node names and inputs of the ComfyUI core nodes, used so the app knows them before it connects to ComfyUI | Derived from ComfyUI (GPL-3.0). These are interface descriptions only, with no ComfyUI code |

## Downloaded at install time (not redistributed)

| Component | Source | Licence |
|---|---|---|
| llama.cpp (`llama-server` and its libraries: CPU, Vulkan or CUDA build) | github.com/ggml-org/llama.cpp releases | MIT |
| NVIDIA CUDA runtime DLLs (only with the Windows CUDA build) | the same llama.cpp release | NVIDIA CUDA Toolkit EULA (redistributable runtime) |
| Python 3.12 for Windows (NuGet `python` / `pythonarm64` package) | nuget.org | Python Software Foundation License 2.0 |
| Recommended model: `huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF` (based on `Qwen/Qwen3.8-27B`) | huggingface.co | Apache-2.0, as stated on the model page. **Check it before use.** |
| Other models you pick from the search | huggingface.co | Each model's own licence, shown on the model page linked during setup |
| Python packages: requests, PyYAML, beautifulsoup4, ddgs, FastAPI, Uvicorn, python-multipart, mcp and their dependencies | pypi.org | Their own licences (Apache-2.0, MIT, BSD) |
| **Optional fresh ComfyUI install**: the ComfyUI Windows portable build (AMD, Intel or NVIDIA), or a git checkout of the release tag on Linux | github.com/Comfy-Org/ComfyUI | GPL-3.0 |
| PyTorch and ComfyUI's Python requirements (part of the ComfyUI install) | pypi.org / download.pytorch.org | BSD-3-Clause (PyTorch) and their own licences |
