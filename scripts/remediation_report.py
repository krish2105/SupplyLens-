"""Render docs/remediation/register.json into docs/remediation/REGISTER.md (the JSON is the source of truth)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
reg = json.loads((ROOT / "docs/remediation/register.json").read_text())
lines = [
    "# Remediation register (22 CTO-audit findings)",
    "",
    f"Generated from `register.json`. Audit snapshot: {reg['audit_snapshot']}. Revalidated at `{reg['revalidated_at_commit']}` "
    f"on {reg['revalidated_on']}. Code status and verification are separate: *fixed* means the code changed; "
    "*verified* names the level of evidence that ran.",
    "",
    "| ID | Title | At revalidation | Code | Verification | Tests / evidence | Requirements |",
    "|---|---|---|---|---|---|---|",
]
for f in reg["findings"]:
    tests = "<br>".join(f.get("tests", [])) or "—"
    req = ", ".join(f.get("requirements", [])) or "—"
    lines.append(f"| {f['id']} | {f['title']} | {f['revalidation']} | {f['code_status']} | {f['verification']} | {tests} | {req} |")
lines += ["", "## Notes per finding", ""]
for f in reg["findings"]:
    lines.append(f"### {f['id']} — {f['title']}")
    lines.append(f"- **Found at HEAD:** {f['revalidation_note']}")
    if f.get("resolution"):
        lines.append(f"- **Resolution:** {f['resolution']}")
    if f.get("blockers"):
        lines.append(f"- **Blockers / remaining:** {f['blockers']}")
    lines.append("")
(ROOT / "docs/remediation/REGISTER.md").write_text("\n".join(lines))
print(f"rendered {len(reg['findings'])} findings")
