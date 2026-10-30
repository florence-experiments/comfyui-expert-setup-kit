# Samplers, schedulers, CFG and steps

## Quick table (starting points - prefer the model page's values)
| Family | sampler / scheduler | steps | CFG | notes |
|---|---|---|---|---|
| SD1.5 | dpmpp_2m / karras | 20-30 | 6-8 | clip skip 2 for anime |
| SDXL realistic | dpmpp_2m_sde or dpmpp_2m / karras | 25-40 | 3-6 | 1024-class sizes |
| SDXL Lightning/Hyper/DMD2 | per page (euler / lcm / dpmpp_sde, sgm_uniform) | 4-8 | 1-2 | |
| Pony | euler_ancestral or dpmpp_2m / karras | 25 | 6-8 | score tags, clip skip 2 |
| Illustrious / NoobAI | euler_ancestral / normal or karras | 20-30 | 4-7 | v-pred versions differ |
| Flux.1 dev | euler / simple (or beta) | 20-30 | 1 (FluxGuidance 3-3.5) | no negative |
| Flux.1 schnell | euler / simple | 4 | 1 | |
| Chroma | euler or res_multistep / simple or beta | 25-30 | 3-4.5 | real negatives |
| Qwen-Image | euler / simple | 20-50 | 2.5-4 | shift 3.1; Lightning 4/8 steps cfg 1 |
| Qwen-Image-Edit 2509/2511 | euler / simple (beta in image_to_real) | 20-40 | 2.5-4 | Lightning: 4-8 steps cfg 1 |
| Z-Image Turbo | res_multistep / simple | 8 | 1 | |
| Wan 2.2 14B | euler or uni_pc / simple | 2x10 (or 4 w/ lightx2v) | 3.5 (1 w/ lightx2v) | two-stage high/low |

## What the knobs do
- **steps**: more = more refinement, diminishing returns after ~30 for SDXL.
- **CFG**: how strongly the prompt is followed. Too high = burnt, oversaturated, plastic skin. Realism likes lower CFG (3-5 on SDXL).
- **denoise** (img2img / detailers): 1.0 = full redraw, 0.3 = small touch-up, 0.5-0.65 = restyle keeping composition.
- **sampler**: euler (simple, stable), euler_ancestral / *_ancestral / *_sde (add fresh noise = more variety, not convergent), dpmpp_2m (fast convergence), dpmpp_2m_sde (detail, realistic skin), uni_pc, res_multistep, lcm (for LCM/Lightning).
- **scheduler**: karras (SD/SDXL default good), normal, simple (flow models), sgm_uniform (Lightning/Turbo), beta, exponential, ddim_uniform. Some custom packs add more (e.g. `beta57` from RES4LYF - not core).
- **seed** + control_after_generate: "fixed" to reproduce, "randomize" to explore.
- **clip skip** = `CLIPSetLastLayer` stop_at_clip_layer -2.
- **shift** (ModelSamplingAuraFlow/SD3): higher = more global structure, lower = more detail; Qwen 3.1, Wan 5-8.

## Resolution rules
- SDXL family: keep ~1 megapixel and multiples of 64 (832x1216 portrait, 1216x832 landscape, 1024x1024). Go bigger with a second pass (upscale + 0.3-0.45 denoise) not with a huge first pass (duplicated bodies).
- Flux/Qwen/Z-Image handle 1-2 MP natively; multiples of 16.
