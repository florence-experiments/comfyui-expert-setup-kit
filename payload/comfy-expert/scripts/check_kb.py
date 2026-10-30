"""Check that node names written in `backticks` in the knowledge pack really exist
(bundled object_info from ComfyUI 0.34 + ComfyUI-Manager extension-node-map).
Usage: python scripts/check_kb.py   (exit 1 if unknown names are found)"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "comfy_expert" / "knowledge"
oi = json.loads((ROOT / "comfy_expert" / "data" / "object_info_bundled.json").read_text(encoding="utf-8"))
known = set(oi)
enm = ROOT / "cache" / "extension-node-map.json"
if enm.exists():
    for _, (names, _meta) in json.loads(enm.read_text(encoding="utf-8")).items():
        known.update(names)
known |= {"Note", "MarkdownNote", "Reroute", "PrimitiveNode"}
# CamelCase identifiers only (node class names), skip file names / flags / env vars
pat = re.compile(r"`([A-Z][A-Za-z0-9_]*[a-z][A-Za-z0-9_]*)`")
bad = {}
for p in sorted(KB.rglob("*.md")):
    for m in pat.finditer(p.read_text(encoding="utf-8")):
        name = m.group(1)
        if "_" in name and name.upper() == name:
            continue
        if name not in known:
            bad.setdefault(name, set()).add(p.name)
for k, v in sorted(bad.items()):
    print(f"UNKNOWN  {k}  ({', '.join(sorted(v))})")
print(f"checked {len(list(KB.rglob('*.md')))} files; unknown: {len(bad)}")
sys.exit(1 if bad else 0)
