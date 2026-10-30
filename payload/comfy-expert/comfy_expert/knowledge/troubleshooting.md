# Troubleshooting

## Red / missing nodes ("When loading the graph, the following node types were not found")
1. summarize_workflow / validate_workflow -> list of NOT_INSTALLED types.
2. find_node_pack(type) for each -> GitHub pack. Install via ComfyUI-Manager (Custom Nodes Manager > search, or "Install Missing Custom Nodes"), or `git clone <repo>` into ComfyUI\custom_nodes and `python_embeded\python.exe -m pip install -r requirements.txt` (watch for torch lines on AMD). Restart ComfyUI.
3. If no pack is found: the node may be renamed (check did_you_mean in comfy_node_info), from a deleted pack (web_search / github_search the exact name), or a frontend-only/group node. Replace it with an equivalent installed node (edit_workflow replace_node) and validate.
4. "Pack version may differ": widgets_values count mismatch - update the pack or re-check values after loading.

## Missing models ("Value not in list: ckpt_name ...")
- validate_workflow lists missing files + the folder they belong in. Look them up (civitai_by_hash if you have a hash, civitai_search_models, hf_search_models, model_archive_search). Files with a different name already on disk: set the widget to that name.
- After copying files press R (refresh) in ComfyUI. Check extra_model_paths.yaml points to the right base_path.

## Generation failed
- Read the error from comfy_queue_test or the ComfyUI console. Common ones:
  - `Error(s) in loading state_dict` / "size mismatch": model family mismatch (SD1.5 LoRA/ControlNet on SDXL, Flux LoRA on Qwen, wrong CLIP type).
  - `mat1 and mat2 shapes cannot be multiplied`: wrong text encoder / CLIPLoader type, or ControlNet/IPAdapter for another family.
  - `Expected all tensors to be on the same device`: a custom node bug; update it or disable offloading options.
  - Black / NaN image: VAE precision (`--fp32-vae`/`--bf16-vae`), wrong VAE, or fp16 overflow - try bf16.
  - Noisy/grey image: wrong sampler for the model (Lightning model with 30 steps / high CFG; v-pred model without v-pred setting), denoise too low on txt2img.
  - Plastic / burnt image: CFG too high, too many LoRAs, LoRA strength > 1.

## Out of memory on AMD 16 GB
- HIP/torch "out of memory": lower resolution or batch, use GGUF Q4/Q5 or fp8 weights, `VAEDecodeTiled`, unload other apps (browser GPU use, games), `--reserve-vram 2`, `--lowvram`, `--disable-smart-memory`.
- llama-server uses VRAM too! If the LLM (this helper's brain) is running on the same GPU, it competes with ComfyUI. Run llama-server on CPU/RAM (`-ngl 0`), with a smaller model, or stop it while generating big images/videos.
- Qwen-Image / Wan 14B at fp8 exceed 16 GB -> rely on RAM offload (slow) or GGUF.
- Long video (Wan): fewer frames (49/81), 480p, lightx2v 4-step LoRAs.

## Slow
- First run compiles/tunes kernels (MIOpen); second run is the real speed.
- Model reloads each run -> enough RAM? `--disable-smart-memory` off; don't switch checkpoints in one graph.
- Partially offloaded models (shown in console "loaded partially") are much slower - use a smaller quant.

## ComfyUI not reachable
- comfy_status fails -> ComfyUI not started, wrong port, or started with `--listen` on a different address. Default http://127.0.0.1:8188.
