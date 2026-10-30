# ComfyUI Expert Setup Kit

> **Experimental and brand new.** This kit is provided as-is, with no warranty. You use it at your own risk.
> Read [DISCLAIMER.md](DISCLAIMER.md) before you install it.

A step-by-step installer for **ComfyUI Expert with Prompt Artist**, a local AI helper for
[ComfyUI](https://github.com/Comfy-Org/ComfyUI). Everything runs on your own computer. There is no cloud account
and no telemetry.

**What ComfyUI Expert does**

- Chats with you about ComfyUI: nodes, workflows, errors, settings and which model to use.
- Reads your ComfyUI to see which models, custom nodes and workflows you have.
- Searches Civitai, Hugging Face and the web for models and workflows. It asks before it downloads anything.
- **Prompt Artist** turns an idea, or a picture you upload, into a ready-to-paste positive and negative prompt with
  settings. "Fix my result" improves a prompt by comparing it with the picture it made.
- Can queue jobs in your running ComfyUI. It can also run as an MCP server for other AI tools.

**What the installer does**, explaining each step and asking before it acts:

1. **Scans your computer** without changing anything: system, processor, RAM, graphics card and video memory
   (VRAM), and free disk space.
2. Asks for an **install folder**. The default is `ComfyUI-Expert` in your home folder.
3. **Finds your ComfyUI.** It checks for ComfyUI running on this computer (ports 8188, 8000 and others), the
   ComfyUI Desktop app, portable `ComfyUI_windows_portable` folders, and the usual folders on every drive
   (Windows) or in your home folder (Linux). It shows what it found and asks *Use this one?* You can pick one of
   several, type a path, or browse for the folder (Windows). If none is found, you can **install ComfyUI fresh**
   from the official release or skip this step. A chosen folder is accepted only if it contains `main.py` and
   `models/`, or is the Desktop app's data folder. The installer also tests the connection to ComfyUI.
4. **Finds HomeAI** (from the [HomeAI Setup Kit](https://github.com/florence-experiments/homeai-setup-kit)) and
   offers to link the two apps. This step is optional. See [Linking with HomeAI](#linking-with-homeai).
5. **Model choice**: the recommended model, another model from a Hugging Face search sized to your VRAM and RAM,
   a model HomeAI already has, or a `.gguf` file you already have.
6. Offers **shortcuts** with the kit icon: start, stop and uninstall.
7. **Shows the full plan**: what will be downloaded, from where, and how big it is. Nothing is downloaded until you
   type `yes`. Every download is checked against its published SHA-256.

The app starts fresh. It contains no chats, drafts, history or settings from anyone else.

## Requirements

- **Windows 10 or 11 (64-bit)**, or **Linux (x64 or arm64)** with Python 3.9 or newer and `python3-venv`.
- **Any graphics card, or none.** The installer picks the matching llama.cpp build:
  - CUDA for NVIDIA cards;
  - Vulkan for AMD and Intel cards;
  - a CPU-only build if no usable card is found.
- **Recommended model**: about 11.4 GB download and 12 GB free disk space. It fits best on a graphics card with
  **16 GB of video memory or more**. With less, it is split between the card and system RAM and runs slower, or
  you can pick a smaller model from the search.
- **ComfyUI** (optional, but needed for queueing jobs and reading your models). A fresh ComfyUI install needs
  about 2 GB on Windows. On Linux it needs about 6 GB or more (PyTorch) and `git`.
- No admin rights are needed.

### The recommended model

[`huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF`](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF),
file `Huihui-Qwen3.8-27B-abliterated-GSQ-RCO-IQ3_XXS-mtp.gguf` (10.4 GB) plus the vision add-on
`mmproj-model-bf16.gguf` (0.9 GB).

- The app was built and tested with this model.
- It is an uncensored ("abliterated") Qwen3.8 27B, so it does not refuse adult art prompts.
- It can see pictures, which Prompt Artist uses.
- Its built-in MTP head makes replies faster.
- It runs with a 32k context.
- Licence: Apache-2.0, as stated on the model page.

## Install, step by step

### Windows

1. Download this repository: **Code → Download ZIP**. Unzip it somewhere, for example to your Downloads folder.
2. Double-click **`Setup-Windows.cmd`**.
   - If Windows SmartScreen appears, click *More info → Run anyway*. The script is plain text, so you can read it
     first.
   - The setup first downloads its own private copy of Python 3.12 (15 MB, SHA-256 checked) from nuget.org.
     Nothing is installed system-wide.
3. Answer the questions. Press **Enter** to accept the suggested answer, shown in brackets.
4. Check the plan, then type **`yes`**.
5. When setup finishes, start the app with the **ComfyUI Expert** shortcut on your desktop. It opens
   `http://127.0.0.1:7860` in your browser.

### Linux

```bash
sudo apt install python3 python3-venv git   # or your distribution's equivalent
git clone https://github.com/<you>/ComfyUI-Expert-Setup-Kit.git
cd ComfyUI-Expert-Setup-Kit
bash setup-linux.sh
```

Start the app with `~/ComfyUI-Expert/start-comfy-expert.sh` or the **ComfyUI Expert** menu entry, and stop it with
`stop-comfy-expert.sh`.

### What ends up where

| Path inside the install folder | Contents |
|---|---|
| `app/` | The ComfyUI Expert app, its `.venv`, `config.yaml`, `.env` (API keys, optional) and `data/` (your chats) |
| `engine/llama.cpp/` | The AI engine (`llama-server`) |
| `models/` | The downloaded model |
| `python/` | Private Python (Windows only) |
| `logs/` | Logs of the last run |
| `Start ComfyUI Expert.cmd` / `start-comfy-expert.sh` | Starts the AI engine, then the app, then opens the browser |
| `app/start-llama.bat` / `.sh` | Starts only the AI engine, if you want to use it from another program |
| `install.json` | What was installed, used by the uninstaller |

Ports (all on 127.0.0.1 only):

| Port | Used by |
|---|---|
| 8080 | ComfyUI Expert's AI engine |
| 7860 | The app |
| 8765 | MCP server (optional) |
| 8188 | ComfyUI |

If a port is taken by another program, setup picks the next free one. Setup never uses 8081 or 8090, which belong
to HomeAI.

Optional API keys (Civitai, Hugging Face) go in `app/.env`. See `app/.env.example`.

## Linking with HomeAI

If [HomeAI](https://github.com/florence-experiments/homeai-setup-kit) is installed, setup asks whether to link the
two apps. You choose each part separately:

- **Share one AI engine.** ComfyUI Expert's model is added as one more model in HomeAI's AI engine
  (`127.0.0.1:8081`), and ComfyUI Expert talks to that engine instead of starting its own on 8080. The engine keeps
  only one model in memory at a time, so the two apps never fill your video memory twice. You can also tell
  ComfyUI Expert to use a model HomeAI already has, with no extra download.
- **Prompt Artist button in HomeAI.** This adds a "Prompt Artist (ComfyUI)" preset to HomeAI with the same
  instructions and the same fixed safety rule.

Before any HomeAI file is changed, it is copied to `<file>.bak-comfy-expert-<date-time>`. The files that can change
are `engine/models.ini`, `install.json` and `homeai/data/presets.json`. The uninstaller's first question offers to
undo the link. It removes only the model entry and the preset that the kit added. Everything else in HomeAI, and
the backups, are left alone. Automatic linking needs a HomeAI installed with the HomeAI Setup Kit. With a
hand-made HomeAI, ComfyUI Expert simply runs its own engine on a port that doesn't clash.

## The fixed safety rule

**Nothing sexual involving anyone under 18.** This rule is part of the app's code and is put in front of every
request to the model. No setting, `.env` entry, prompt file or web page option can remove it. It is the only
restriction the app adds itself.

## Uninstall

Use the **Uninstall ComfyUI Expert** shortcut, or run `Uninstall ComfyUI Expert.cmd` (Windows) or
`uninstall-comfy-expert.sh` (Linux). The uninstaller asks before each item, and anything you don't confirm stays.
It covers, in order:

1. the HomeAI link;
2. the shortcuts;
3. a ComfyUI that the kit installed (with everything in it);
4. the model;
5. your chats;
6. the rest of the folder.

A ComfyUI you already had is never touched.

## Troubleshooting

| Problem | What to do |
|---|---|
| "Python download did not match its SHA-256" | The download was damaged or changed. Try again later. Setup stops rather than run an unverified file. |
| Setup cannot reach github.com / huggingface.co | Check your internet connection, proxy or firewall. You can run setup again: downloads resume where they stopped. |
| A Hugging Face model needs a login | Set the `HF_TOKEN` environment variable before running setup. The token is used for that session and not saved. |
| The app opens but says the AI is not answering | The model can take a minute to load. Look in `logs/llama.log`. If the model is too big for your memory, run setup again and choose a smaller one. |
| "Port 8080 is used by another program" | Run setup again. It picks a free port. |
| ComfyUI not found | Choose *t* to type the folder that contains `main.py`, or connect it later in the app's Settings. Start ComfyUI before you queue jobs. |
| Fresh ComfyUI won't unpack on Windows | Install [7-Zip](https://7-zip.org) and run setup again. |
| Linux: "could not create a venv" | `sudo apt install python3-venv` |
| Slow replies | Normal on the processor or when the model is split between the graphics card and RAM. A smaller model from the search helps. |
| Linked with HomeAI and replies stop | Start HomeAI first, or let the ComfyUI Expert shortcut start HomeAI's engine. Only one model is loaded at a time, so switching between the apps reloads it. |

`help.txt` has a short version of this guide.

## Credits

ComfyUI Expert is built on [ComfyUI](https://github.com/Comfy-Org/ComfyUI) (Comfy Org),
[llama.cpp](https://github.com/ggml-org/llama.cpp), the model publishers on [Hugging Face](https://huggingface.co)
(the recommended model is by huihui-ai, based on Qwen), and the Python packages listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Licence: [MIT](LICENSE).

<sub>Built by Florence for the community.</sub>
