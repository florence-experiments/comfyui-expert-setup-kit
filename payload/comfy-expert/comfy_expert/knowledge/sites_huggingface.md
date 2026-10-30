# Hugging Face (huggingface.co)

- Search: hf_search_models (author=Comfy-Org, city96, QuantStack, unsloth, Kijai, lightx2v, black-forest-labs, Qwen, Wan-AI, h94, Bingsu, ...). Filter "gguf" for GGUF repos.
- Files: hf_list_files repo [path] [match] -> exact paths, sizes, SHA256 (LFS oid) and download URLs `https://huggingface.co/<repo>/resolve/main/<path>`.
- Gated repos (Flux.1-dev original, some SD3 / Llama): accept the licence on the website while logged in, create a READ token at https://huggingface.co/settings/tokens, put `HF_TOKEN=hf_...` in `.env`.
- Comfy-Org "repackaged" repos have files already split for ComfyUI folders: `split_files/diffusion_models`, `split_files/text_encoders`, `split_files/vae`, `split_files/loras`. Examples: Comfy-Org/Qwen-Image_ComfyUI, Comfy-Org/Qwen-Image-Edit_ComfyUI, Comfy-Org/Wan_2.2_ComfyUI_Repackaged (now redirects to Comfy-Org/Wan-2.2), Comfy-Org/flux1-dev (-> Comfy-Org/Flux-1-Dev), Comfy-Org/z_image_turbo (-> Comfy-Org/Z-Image-Turbo). Comfy-Org renamed many repos in 2026; old URLs redirect, so links in older workflows still work. Always list files - names change between releases.
- GGUF providers: city96 (Flux, Qwen-Image, Wan, T5), QuantStack (Qwen-Image(-Edit), Wan 2.2), unsloth (Qwen-Image-Edit-2511, others). Kijai/WanVideo_comfy hosts many Wan helpers (fp8, LoRAs, text encoders).
- Upscalers / detectors: Kim2091/UltraSharp (4x-UltraSharp), Bingsu/adetailer (face_yolov8m.pt etc.), h94/IP-Adapter.
- ModelScope (modelscope.cn) is the Chinese equivalent (often has Qwen/Wan first) - use web_search/fetch_url.
