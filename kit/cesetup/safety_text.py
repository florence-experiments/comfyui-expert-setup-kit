"""The app's fixed safety rule, read from the app's own code (payload/comfy-expert/comfy_expert/safety.py)
so the HomeAI Prompt Artist button gets exactly the same rule."""
import os
import re

from .util import PAYLOAD_DIR

_src = open(os.path.join(PAYLOAD_DIR, "comfy-expert", "comfy_expert", "safety.py"), encoding="utf-8").read()
SAFETY_RULE = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', re.search(r"SAFETY_RULE = \((.*?)\n\)", _src, re.S).group(1)))
