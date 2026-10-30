# Core nodes cheat-sheet (built into ComfyUI)
Always confirm details with comfy_node_info - packs/versions change. Outputs are listed as SLOT:TYPE.

## Loaders
- `CheckpointLoaderSimple` (ckpt_name) -> 0:MODEL 1:CLIP 2:VAE. For SD1.5/SDXL/Pony/Illustrious all-in-one checkpoints (models/checkpoints).
- `UNETLoader` (unet_name, weight_dtype) -> MODEL. Diffusion-only models (Flux, Qwen-Image, Wan, Z-Image...), folder diffusion_models (alias unet). weight_dtype `fp8_e4m3fn` loads a bf16 file as fp8 to save VRAM.
- `UnetLoaderGGUF` (ComfyUI-GGUF pack, city96) - .gguf diffusion models from models/unet (or diffusion_models). `CLIPLoaderGGUF`/`DualCLIPLoaderGGUF` for GGUF text encoders.
- `CLIPLoader` (clip_name, type, device) -> CLIP. Single text encoder; `type` must match the model: `qwen_image`, `wan`, `stable_diffusion`, `sd3`, `flux2`, `lumina2`, `chroma`, `hidream`... (check combo list).
- `DualCLIPLoader` (clip_name1, clip_name2, type) e.g. Flux.1: clip_l + t5xxl, type `flux`. `TripleCLIPLoader` for SD3.
- `VAELoader` (vae_name) -> VAE. Flux.1/Z-Image: ae.safetensors; Qwen-Image: qwen_image_vae.safetensors; Wan 2.1/2.2-14B: wan_2.1_vae.safetensors; Wan 2.2 5B: wan2.2_vae.safetensors.
- `LoraLoader` (MODEL, CLIP, lora_name, strength_model, strength_clip) -> MODEL, CLIP. `LoraLoaderModelOnly` for models without CLIP in the loader (Flux/Qwen/Wan).
- `CLIPVisionLoader`, `ControlNetLoader`, `UpscaleModelLoader` (models/upscale_models), `StyleModelLoader`.
- `CLIPSetLastLayer` (stop_at_clip_layer -2 = "clip skip 2", common for Pony/Illustrious/anime SD1.5).

## Conditioning / prompts
- `CLIPTextEncode` (clip, text) -> CONDITIONING. Positive and negative are two separate nodes.
- `ConditioningZeroOut` - "empty" negative for Flux/Z-Image style models.
- `FluxGuidance` (guidance 2.5-4) - Flux distilled guidance, use KSampler cfg 1.0.
- `TextEncodeQwenImageEdit` / `TextEncodeQwenImageEditPlus` (clip, vae, image1..3, prompt) - Qwen-Image-Edit (2509/2511 use Plus).
- `ReferenceLatent`, `FluxKontextMultiReferenceLatentMethod` - reference image conditioning for Kontext/Flux.2/Qwen-Edit 2511.
- `ControlNetApplyAdvanced` (positive, negative, control_net, image, vae, strength, start_percent, end_percent).

## Latents / images
- `EmptyLatentImage` (width, height, batch_size) - SD1.5/SDXL. `EmptySD3LatentImage` - SD3/Flux.1/Qwen-Image/Z-Image. `EmptyFlux2LatentImage` - Flux.2. `EmptyHunyuanLatentVideo` - Wan 2.2 14B T2V. `WanImageToVideo`, `Wan22ImageToVideoLatent` (5B).
- `VAEEncode` / `VAEDecode` (+ `VAEDecodeTiled` / `VAEEncodeTiled` for low VRAM). `VAEEncodeForInpaint` (needs denoise 1.0). `SetLatentNoiseMask` (inpaint with any denoise). `InpaintModelConditioning`.
- `LoadImage` -> IMAGE, MASK (mask drawn in the MaskEditor). `SaveImage`, `PreviewImage`.
- `ImageScale`, `ImageScaleBy`, `ImageScaleToTotalPixels` (megapixels), `ImageUpscaleWithModel`, `LatentUpscaleBy`, `FluxKontextImageScale`.
- `GrowMask`, `ImageCompositeMasked`, `ImageStitch`.

## Sampling
- `KSampler` (model, positive, negative, latent_image, seed, control_after_generate, steps, cfg, sampler_name, scheduler, denoise).
- `KSamplerAdvanced` (add_noise, noise_seed, steps, cfg, sampler, scheduler, start_at_step, end_at_step, return_with_leftover_noise) - used for 2-stage (Wan 2.2 high/low noise, SDXL refiner).
- Custom sampling: `SamplerCustomAdvanced` + `RandomNoise` + `BasicGuider`/`CFGGuider` + `KSamplerSelect` + `BasicScheduler`/`Flux2Scheduler`.
- `ModelSamplingAuraFlow` (shift ~3.1, Qwen-Image / Z-Image), `ModelSamplingSD3` (shift ~5-8, Wan), `ModelSamplingFlux`, `ModelSamplingDiscrete`.
- `CFGNorm` (Qwen-Image-Edit official templates), `RescaleCFG`.

## Common custom node packs (check they are installed!)
- ComfyUI-Manager (install/update nodes, "Install Missing Custom Nodes").
- ComfyUI-Impact-Pack + ComfyUI-Impact-Subpack: `FaceDetailer`, `UltralyticsDetectorProvider` (Subpack), `SAMLoader`, `DetailerForEach`.
- ComfyUI_IPAdapter_plus (cubiq): `IPAdapterUnifiedLoader`, `IPAdapter`, `IPAdapterAdvanced`, `IPAdapterFaceID`.
- comfyui_controlnet_aux (Fannovel16): preprocessors like `DWPreprocessor`, `DepthAnythingV2Preprocessor`, `CannyEdgePreprocessor` (core also has `Canny`).
- ComfyUI-GGUF (city96): `UnetLoaderGGUF`, `CLIPLoaderGGUF`.
- rgthree-comfy: `Power Lora Loader (rgthree)`, fast groups bypasser, seed, image comparer.
- was-node-suite, ComfyUI-KJNodes, ComfyUI-VideoHelperSuite (`VHS_VideoCombine`), ComfyUI_UltimateSDUpscale (`UltimateSDUpscale`), comfyui-easy-use, ComfyUI-Custom-Scripts (pysssss).
