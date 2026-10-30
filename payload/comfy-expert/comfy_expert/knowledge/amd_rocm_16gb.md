# AMD (RX 9070 XT, RDNA4, 16 GB) + ROCm on Windows: tips

Sources: docs.comfy.org portable AMD page, AMD ROCm blog "ComfyUI on Radeon RX 9000", community RX 9070 XT tuning notes (2026). Windows ROCm is still marked experimental - things that work on NVIDIA may not on AMD.

## Launching
- Portable AMD build: `run_amd_gpu.bat` (= `python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build`).
- Make a copy (e.g. `run_amd_tuned.bat`) instead of editing the original. Useful additions people report on RX 9070 XT (test one at a time):
```bat
set COMFYUI_ENABLE_MIOPEN=1
set MIOPEN_FIND_MODE=FAST
set "MIOPEN_USER_DB_PATH=%~dp0.miopen_db"
set TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1
set PYTORCH_HIP_ALLOC_CONF=expandable_segments:True
.\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --use-pytorch-cross-attention --reserve-vram 1.5
```
- `--reserve-vram N` (GB) keeps room for Windows/desktop/browser. AMD suggests 3 for 16 GB cards on Linux; 1-2 is common on Windows. Raise it if you get OOM at the end of a run or driver timeouts.
- `--lowvram` / `--novram` force offloading (slower, but rescues big models). `--disable-smart-memory` unloads models between runs (more stable, slower). `--cache-none` lowers RAM use.
- `--fp16-vae` / `--bf16-vae` / `--fp32-vae`: if VAE decode gives black/NaN images, try `--fp32-vae` or `--bf16-vae`.
- First run of a new resolution/model is slow (MIOpen kernel search); later runs are faster. Keep `MIOPEN_USER_DB_PATH` so the tuning is remembered.

## What fits in 16 GB (rough)
- SD1.5 / SDXL / Pony / Illustrious fp16: yes, easily, incl. LoRAs, ControlNet, IPAdapter, FaceDetailer. 2x upscale fine; 4K needs tiled.
- Flux.1 dev: fp8 (~12 GB) or GGUF Q4_K_S-Q8_0 (6.8-12.7 GB). t5xxl fp8 text encoder. Works with smart offloading.
- Qwen-Image / Qwen-Image-Edit (20B): fp8 files are ~19-20 GB -> ComfyUI will partially offload to RAM (lots of system RAM, e.g. 64 GB, makes this usable but slower). GGUF Q4_K_M (~12 GB) or Q3_K_M (~9 GB) fit much better. Text encoder qwen_2.5_vl_7b fp8 (8.7 GB) is unloaded after encoding.
- Wan 2.2 14B: fp8 (~14 GB per expert) or GGUF Q4-Q6; only one expert is in VRAM at a time. 480p-720p, 81 frames, lightx2v 4-step LoRAs. VAEDecodeTiled for long clips.
- Z-Image Turbo (6B): comfortable.

## GGUF vs fp8 on AMD
- **GGUF** (ComfyUI-GGUF, `UnetLoaderGGUF`): smallest files, works everywhere, slight dequant overhead. Q8_0 ~ fp16 quality; Q5_K_M/Q6_K very good; Q4_K_M good; Q3 visible loss. Best choice when a model doesn't fit.
- **fp8 (e4m3fn / *_scaled / fp8mixed)**: weights stored in 8-bit, computed in bf16/fp16. Saves VRAM on AMD; speed-ups from native fp8 math depend on ROCm/PyTorch support for RDNA4 - don't promise them.
- **nvfp4 / int8_convrot / "nunchaku" (SVDQuant)** files are NVIDIA/CUDA-oriented - avoid on AMD unless the page says ROCm works.
- bf16/fp16 full models: best quality, only if they fit.

## Things that often break on AMD Windows
- Packs needing CUDA-only libs: xformers, flash-attn CUDA builds, SageAttention CUDA, bitsandbytes (NF4), nunchaku, TensorRT, onnxruntime-gpu (CUDA) -> use alternatives (onnxruntime CPU/DirectML, GGUF instead of NF4).
- insightface (IPAdapter FaceID, ReActor, InstantID) - needs a prebuilt wheel for the embedded Python version; may run on CPU.
- `torch.compile` / Triton nodes - experimental on Windows ROCm.
- Out-of-memory during VAE decode -> `VAEDecodeTiled` (tile 512, overlap 64).
- Driver timeout / black screen on long jobs -> raise `--reserve-vram`, lower resolution, update the Adrenalin driver that matches the ROCm build.

## Installing pip packages for custom nodes (ComfyUI's Python only)
`python_embeded\python.exe -m pip install -r ComfyUI\custom_nodes\<pack>\requirements.txt` - check the requirements don't replace torch (lines like `torch==`/`torchvision` would install a CUDA build and break ROCm). If a pack does that, install the other lines manually.
