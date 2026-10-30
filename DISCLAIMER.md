# Disclaimer

**The ComfyUI Expert Setup Kit is new, experimental software. It is provided "as is", with no warranty of any
kind. You use it at your own risk.**

- **You choose the model.** The recommended model and the models found by the Hugging Face search were published
  by other people. This kit did not make them, has not checked them, and does not endorse them. You are
  responsible for the models you download and for how you use them and their output. You must also follow each
  model's licence and the laws where you live.
- **Uncensored ("abliterated") models.** The recommended model is one of these. Most of its refusal behaviour has
  been removed. It can produce offensive, harmful, biased or simply wrong output. Do not rely on AI output for
  medical, legal, financial or safety decisions.
- **One fixed safety rule.** Every request the app sends to a model includes a rule that forbids sexual content
  involving anyone under 18. The rule is part of the app's code. It cannot be switched off from settings, `.env`,
  the web page or prompt files. It is the only restriction the app itself adds.
- **ComfyUI.** ComfyUI Expert can read your ComfyUI folders. When you ask it to, it can also download models into
  them and queue jobs. It always asks before it downloads, installs or deletes anything. If you choose a fresh
  ComfyUI install, the official ComfyUI release is used. That release has its own licence and terms.
- **HomeAI link (optional).** When you link the two apps, the kit changes HomeAI's `engine/models.ini`,
  `install.json` and `homeai/data/presets.json`. Each file is backed up first. The uninstaller removes only what
  the kit added.
- **Privacy.** Everything runs on your computer, and the kit sends no telemetry. The kit uses the network only for
  downloads you approve (GitHub, Hugging Face, PyPI, nuget.org). The app uses it only for web or model searches you
  ask for.
- **No affiliation.** This project is not affiliated with or endorsed by Comfy Org/ComfyUI, llama.cpp/ggml.ai,
  Hugging Face, Qwen/Alibaba, huihui-ai, Microsoft or any model publisher. Their names are used only to identify
  their software.

The authors and contributors accept no liability for any damage, loss or legal consequence that results from using
this software, or any model or output obtained with it.
