# Model folders: where each file type goes

Inside `ComfyUI\models\` (and in every extra path from `extra_model_paths.yaml`, e.g. `D:\AI\models\`):

| Folder | What | Loader node |
|---|---|---|
| checkpoints | all-in-one SD1.5/SDXL/Pony/Illustrious .safetensors | CheckpointLoaderSimple |
| diffusion_models (old name: unet) | diffusion-only models: Flux, Qwen-Image, Wan, Z-Image, HiDream; also .gguf for UnetLoaderGGUF (unet folder) | UNETLoader, UnetLoaderGGUF |
| text_encoders (old name: clip) | t5xxl, clip_l, clip_g, umt5_xxl, qwen_2.5_vl_7b, qwen_3_4b, mistral... | CLIPLoader, DualCLIPLoader |
| vae | ae.safetensors, sdxl_vae, qwen_image_vae, wan_2.1_vae | VAELoader |
| loras | LoRA / LyCORIS / LoCon / DoRA files | LoraLoader, LoraLoaderModelOnly |
| embeddings | textual inversions (use `embedding:name` in the prompt) | - |
| controlnet | ControlNet / T2I-Adapter / union models | ControlNetLoader |
| clip_vision | CLIP-ViT-H-14..., sigclip_vision_patch14_384 | CLIPVisionLoader |
| ipadapter | ip-adapter-*.safetensors (IPAdapter_plus pack) | IPAdapterUnifiedLoader / IPAdapterModelLoader |
| upscale_models | 4x-UltraSharp.pth, RealESRGAN etc. | UpscaleModelLoader |
| ultralytics/bbox, ultralytics/segm | face_yolov8m.pt, hand_yolov8s.pt, person_yolov8m-seg.pt | UltralyticsDetectorProvider |
| sams | sam_vit_b_01ec64.pth | SAMLoader |
| style_models | Flux Redux | StyleModelLoader |
| model_patches | DiffSynth / Qwen ControlNet patches (newer core) | ModelPatchLoader |
| configs, hypernetworks, gligen, photomaker, vae_approx, latent_upscale_models, audio_encoders | rarer | - |

Notes
- ComfyUI shows subfolders: a file in `loras\sdxl\x.safetensors` is selected as `sdxl\x.safetensors` (Windows) - widget values must include the subfolder.
- `extra_model_paths.yaml` example for a shared folder:
```yaml
shared_models:
  base_path: D:/AI/models/
  checkpoints: checkpoints
  diffusion_models: |
    diffusion_models
    unet
  text_encoders: |
    text_encoders
    clip
  loras: loras
  vae: vae
  controlnet: controlnet
  upscale_models: upscale_models
  clip_vision: clip_vision
  ipadapter: ipadapter
  ultralytics: ultralytics
  sams: sams
```
- After adding files press **R** in ComfyUI (refresh) or restart so combo lists update.
- Civitai type -> folder: Checkpoint -> checkpoints, LORA/LoCon/DoRA -> loras, TextualInversion -> embeddings, Controlnet -> controlnet, Upscaler -> upscale_models, VAE -> vae, MotionModule -> animatediff_models.
