"""Write the FastAPI OpenAPI document deterministically (sorted keys) for contract checks."""
import json
import sys
from pathlib import Path

from supplylens.api.app import app

out = Path(sys.argv[1] if len(sys.argv) > 1 else "packages/contracts/openapi.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(f"wrote {out} ({len(app.openapi()['paths'])} paths)")
