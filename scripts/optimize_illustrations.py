"""Build the web derivatives of the SupplyLens illustration pack and the app asset manifest.

Sources stay untouched in design/source-assets/supplylens/ (byte-identical to the supplied files; their SHA-256 is
checked against the manifest). Derivatives are lossless-alpha WebP at 2x the largest display size, written to
apps/web/public/illustrations/supplylens/. Phase 8: the owner replaced A02, A13 and A16 (withheld under D-040: document
lines and a chart, joined suppliers, kraft cartons) with files made for the Phase 8 briefs and added A17 and A18; the
owner approved them on 2026-11-10 (D-108). A17 and A18 were held back until their screens existed; since 2026-11-10 they
are shown in Policies > Extracted terms (nothing found) and the status assistant drawer (first use).

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
# Items whose source is present but must not be published, with the reason (none since the Phase 8 replacements).
EXCLUDED: dict[str, str] = {}
# Pieces published as files but not rendered by any screen yet (none since the Phase 8 screens were built).
RESERVED: set[str] = set()
USAGE = {"A01": "login page (sign-in): square crop of the subject filling the art panel (about 450-470 px), hidden below 768 px", "A03": "inventory: authorized empty scope",
         "A04": "policies: authorized library has no documents", "A05": "forecast lab: no forecast run for the context",
         "A06": "scenario studio: no saved scenarios", "A07": "filtered lists: zero matches",
         "A08": "approvals/exceptions: zero pending items in the visible filters",
         "A09": "connection banner / error state: detected network failure with retry",
         "A10": "server-denied access (403/404 restricted)", "A11": "administration: no connectors configured",
         "A12": "policies: amendment-impact introduction", "A14": "research: no experiments recorded",
         "A15": "investigations: no runs in authorized scope",
         "A02": "data admission: no dataset and no import batches, user may import (tenant admin, not the locked demo)",
         "A13": "supplier market: no award data imported into the Contract research workspace",
         "A16": "value: the ledger has no study yet",
         "A17": "Policies > document reader > Extracted terms: the rules found no field in this version (empty_scope); never for loading or errors",
         "A18": "Status assistant drawer, before the first question (first_run); never for answers, withheld answers or errors"}


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
        # A01 at its native 1536 px: the sign-in page crops it to the subject (about two thirds of the width) at ~470 CSS
        # px, which needs ~940 source pixels on a 2x screen
        width = 1536 if a["id"] == "A01" else 360
        with Image.open(src) as im:
            im = im.convert("RGBA")
            h = round(im.height * width / im.width)
            small = im.resize((width, h), Image.Resampling.LANCZOS)
            name = a["filename"].replace(".png", ".webp")
            dest = OUT / name
            small.save(dest, "WEBP", quality=86, method=6, exact=True)
        entries.append({**entry, "published": True, "path": f"/illustrations/supplylens/{name}", "width": width,
                        "height": h, "bytes": dest.stat().st_size, "sha256": sha(dest), "usage": USAGE[a["id"]],
                        "rendered": a["id"] not in RESERVED,
                        "review": "prepared at the documented size; not rendered until its screen exists" if a["id"] in RESERVED
                        else "integrated at the documented size; reviewed in light and dark themes in the running app"})
    MANIFEST.write_text(json.dumps({"generated_by": "scripts/optimize_illustrations.py", "assets": entries}, indent=2) + "\n")
    print(f"published {sum(e['published'] for e in entries)} of {len(entries)}; manifest {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
