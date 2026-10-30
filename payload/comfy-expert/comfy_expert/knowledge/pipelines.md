# Pipelines: LoRA, IPAdapter, ControlNet, FaceDetailer, upscaling, inpaint

## LoRA
- SDXL/SD1.5: `LoraLoader` between the checkpoint and everything else: ckpt MODEL -> LoraLoader.model, ckpt CLIP -> LoraLoader.clip; LoraLoader MODEL -> KSampler.model (and FaceDetailer.model), LoraLoader CLIP -> every CLIPTextEncode.clip. Chain several LoraLoaders in a row.
- Flux/Qwen/Wan/Z-Image: `LoraLoaderModelOnly` after the UNET loader (and before ModelSampling* in many templates - either order works).
- Strength 0.6-1.0 typical; character LoRAs 0.7-0.9; style LoRAs 0.4-0.8; stacking many >1.0 total causes artifacts.
- Trigger words: civitai_get_model returns `trigger_words` - put them in the positive prompt.
- LoRA must match the base family (SDXL LoRA on Pony/Illustrious works only partly; SD1.5 LoRA on SDXL does nothing/errors).
- rgthree `Power Lora Loader (rgthree)` stores LoRAs as dict rows in widgets_values ({on, lora, strength}).

## IPAdapter (cubiq ComfyUI_IPAdapter_plus) - character / style reference for SD1.5/SDXL
- Easiest: `IPAdapterUnifiedLoader` (preset: STANDARD, PLUS, PLUS FACE (portraits), VIT-G...) takes MODEL -> outputs MODEL + IPADAPTER -> `IPAdapter` (model, ipadapter, image, weight, start_at, end_at, weight_type) -> MODEL to KSampler.
- Files (standard names the unified loader looks for): models/ipadapter/ip-adapter-plus-face_sdxl_vit-h.safetensors, ip-adapter-plus_sdxl_vit-h.safetensors (from h94/IP-Adapter sdxl_models/), models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors (= h94/IP-Adapter models/image_encoder/model.safetensors renamed). Check the pack README with fetch_url for the exact current list.
- FaceID variants need insightface (hard to install on Windows/AMD - avoid unless needed).
- weight 0.5-0.85; end_at 0.7-0.9 to leave room for the prompt. Use clean square-ish face crops as reference.
- Flux has its own (XLabs/InstantX "Flux IP-Adapter", Redux via StyleModelLoader); Qwen-Image-Edit uses the reference images directly (image1..3).

## ControlNet (pose, depth, canny, lineart, tile)
- `ControlNetLoader` (models/controlnet) + `ControlNetApplyAdvanced` (positive, negative, control_net, image[, vae]) -> new positive/negative -> KSampler.
- Preprocessors: core `Canny`; comfyui_controlnet_aux for `DWPreprocessor` (pose), `DepthAnythingV2Preprocessor`, `LineArtPreprocessor`, etc.
- SDXL: xinsir/controlnet-union-sdxl-1.0 (one model, many modes; with `SetUnionControlNetType`), or individual xinsir models. Flux: InstantX/Shakker union. Qwen-Image: InstantX Qwen-Image ControlNet / DiffSynth model patches (see official templates).
- strength 0.4-0.8, end_percent 0.6-0.9 for realism (lets the model fix details).
- Anime->realistic with ControlNet: extract depth/pose/lineart from the anime picture, generate with a realistic checkpoint and a photo prompt.

## FaceDetailer (Impact Pack + Impact Subpack)
- `UltralyticsDetectorProvider` (model_name `bbox/face_yolov8m.pt`, from Bingsu/adetailer, in models/ultralytics/bbox) -> BBOX_DETECTOR -> `FaceDetailer`.
- FaceDetailer inputs: image, model, clip, vae, positive, negative, bbox_detector (+ optional sam_model_opt from `SAMLoader` sam_vit_b_01ec64.pth in models/sams, segm_detector_opt).
- Realistic faces: guide_size 512-768, denoise 0.35-0.5, steps 20, same sampler as the main pass, feather 5, bbox_crop_factor 3. Too high denoise changes identity.
- Also: hand_yolov8s.pt for hands, person_yolov8m-seg.pt (segm) for bodies.

## Upscaling
1. **Model upscale (fast, no AI redraw):** `UpscaleModelLoader` (4x-UltraSharp.pth, RealESRGAN_x4plus, 4x_NMKD-Siax_200k, 4x-ClearRealityV1...) -> `ImageUpscaleWithModel` -> `ImageScaleBy` 0.5 for 2x total.
2. **Hi-res fix (adds real detail):** model or latent upscale to 1.5-2x, then VAEEncode -> KSampler denoise 0.3-0.45 -> VAEDecode. On SDXL keep tiles or total size reasonable on 16 GB (VAEDecodeTiled helps).
3. **Tiled redraw:** `UltimateSDUpscale` (ComfyUI_UltimateSDUpscale pack) with tile ControlNet for 4K+.
4. **SeedVR2 / Topaz-like video+image restorers**: see official templates (utility_seedvr2*).

## Inpainting
- Any checkpoint: VAEEncode + `SetLatentNoiseMask` (mask from LoadImage MaskEditor, `GrowMask` 6-12 px), denoise 0.6-0.9.
- Inpaint checkpoints or `VAEEncodeForInpaint` (denoise must be 1.0) / `InpaintModelConditioning`.
- Flux Fill, Qwen-Image InstantX inpainting ControlNet, Qwen-Image-Edit (just describe the change, no mask needed).

## Img2img restyle
LoadImage -> ImageScaleToTotalPixels(1.0 MP) -> VAEEncode -> KSampler(denoise 0.45-0.7) with the new checkpoint + new prompt.

## Two-pass realistic pipeline (good default on 16 GB)
txt2img SDXL realistic (832x1216, CFG 4, 30 steps) -> FaceDetailer (denoise 0.4) -> 4x-UltraSharp + scale 0.5 -> optional second KSampler pass at denoise 0.3 -> SaveImage. Template: sdxl_facedetailer_upscale.
