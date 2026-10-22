"""Build the web derivatives of the SupplyLens illustration pack and the app asset manifest.

Sources stay untouched in design/source-assets/supplylens/ (byte-identical to the supplied pack; their SHA-256 is checked
against the pack manifest). Derivatives are lossless-alpha WebP at 2x the largest display size, written to
apps/web/public/illustrations/supplylens/. Three assets are not published (owner decision D-041): A02 shows document
lines and a chart where a blank sheet was briefed, A13 shows joined suppliers where unjoined connectors were briefed, and
A16 uses kraft cartons that read as a value claim; those states use HTML/icon fallbacks instead.

uv run python scripts/optimize_illustrations.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "design" / "source-assets" / "supplylens"
OUT = ROOT / "apps" / "web" / "public" / "illustrations" / "supplylens"
MANIFEST = ROOT / "apps" / "web" / "lib" / "illustrations.json"
EXCLUDED = {"A02": "shows document lines and a pie chart; the brief asked for a blank sheet",
            "A13": "shows connected suppliers; the brief asked for unjoined connectors",
            "A16": "kraft cartons read as a business-value signal; the brief asked for neutral off-white"}
USAGE = {"A01": "login page (sign-in), 360-560 px, hidden below 768 px", "A03": "inventory: authorized empty scope",
         "A04": "policies: authorized library has no documents", "A05": "forecast lab: no forecast run for the context",
         "A06": "scenario studio: no saved scenarios", "A07": "filtered lists: zero matches",
         "A08": "approvals/exceptions: zero pending items in the visible filters",
         "A09": "connection banner / error state: detected network failure with retry",
         "A10": "server-denied access (403/404 restricted)", "A11": "administration: no connectors configured",
         "A12": "policies: amendment-impact introduction", "A14": "research: no experiments recorded",
         "A15": "investigations: no runs in authorized scope"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    pack = json.loads((SRC / "source_manifest.json").read_text())["assets"]
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for a in pack:
        src = SRC / a["filename"]
        digest = sha(src)
        if digest != a["sha256"]:
            raise SystemExit(f"{a['id']} {a['filename']}: source hash differs from the pack manifest")
        entry = {"id": a["id"], "source": str(src.relative_to(ROOT)), "source_sha256": digest,
                 "show_only_when": a["show_only_when"], "alt": "", "decorative": True,
                 "pack_quality_notes": a.get("quality_notes")}
        if a["id"] in EXCLUDED:
            entries.append({**entry, "published": False, "review": f"not published: {EXCLUDED[a['id']]}",
                            "fallback": "HTML text with a lucide icon"})
            continue
        width = 1120 if a["id"] == "A01" else 360
        with Image.open(src) as im:
            im = im.convert("RGBA")
            h = round(im.height * width / im.width)
            small = im.resize((width, h), Image.Resampling.LANCZOS)
            name = a["filename"].replace(".png", ".webp")
            dest = OUT / name
            small.save(dest, "WEBP", quality=86, method=6, exact=True)
        entries.append({**entry, "published": True, "path": f"/illustrations/supplylens/{name}", "width": width,
                        "height": h, "bytes": dest.stat().st_size, "sha256": sha(dest), "usage": USAGE[a["id"]],
                        "review": "integrated at the documented size; reviewed in light and dark themes in the running app"})
    MANIFEST.write_text(json.dumps({"generated_by": "scripts/optimize_illustrations.py", "assets": entries}, indent=2) + "\n")
    print(f"published {sum(e['published'] for e in entries)} of {len(entries)}; manifest {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
