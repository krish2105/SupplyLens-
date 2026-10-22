"""Stand-in for the local embedding service, used ONLY by the load test.

Real embedding latency (bge-m3 on a CPU or GPU) cannot be measured in an environment without model weights, and ARC-07
excludes external model calls from the retrieval target. This stub answers /api/embed with deterministic unit vectors
in ~1 ms so the API's real code path (HTTP call, vector literal, pgvector cosine search, fusion) is exercised. The
report states plainly that embedding time is not included.
"""
import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

DIM = 1024


def vec(text: str) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    v = np.random.default_rng(seed).standard_normal(DIM).astype(np.float32)
    return (v / np.linalg.norm(v)).round(5).tolist()


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        inputs = body.get("input") or []
        out = json.dumps({"model": body.get("model"), "embeddings": [vec(t) for t in inputs]}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(out)))
        self.end_headers(); self.wfile.write(out)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 11500), H).serve_forever()
