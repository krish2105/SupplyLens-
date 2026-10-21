#!/usr/bin/env python3
"""SupplyLens public-data acquisition. Standard library only; run with network access.

All resulting downloads are separate from this ZIP. The command records source URLs,
SHA-256 checksums, acquisition times, and fetch outcomes. This is not a rights grant.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "source_manifest.json"
RECEIPTS = ROOT / "data" / "download_receipts.jsonl"
BUF = 1024 * 1024
MAX_SINGLE_FILE = 4 * 1024 ** 3
USER_AGENT = "SupplyLens-Academic-Data-Acquisition/1.0 (+respect publisher license)"


def timestamp():
    return dt.datetime.now(dt.UTC).isoformat()


def load_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))["datasets"]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(BUF), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(dataset: dict, status: str, **details):
    entry = {
        "at_utc": timestamp(), "dataset_id": dataset["id"],
        "status": status, "origin": dataset["origin"],
        "source_url": dataset["source_url"], "license": dataset["license"],
        **details,
    }
    RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    with RECEIPTS.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=True) + "\n")
    return entry


def request_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def download_binary(url: str, target: Path, max_bytes: int = MAX_SINGLE_FILE) -> dict:
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("Only HTTPS downloads are allowed")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size:
        return {"path": str(target.relative_to(ROOT)), "bytes": target.stat().st_size,
                "sha256": hash_file(target), "reused_existing": True}
    fd, tmp_name = tempfile.mkstemp(prefix=".partial-", dir=str(target.parent))
    count = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream,application/zip,*/*"})
            with contextlib.closing(urllib.request.urlopen(req, timeout=120)) as response:
                mime = response.headers.get("Content-Type", "").lower()
                while True:
                    chunk = response.read(BUF)
                    if not chunk:
                        break
                    if count == 0 and ("text/html" in mime or chunk[:512].lstrip().lower().startswith((b"<!doctype html", b"<html"))):
                        raise ValueError("Source returned an HTML page instead of dataset bytes")
                    count += len(chunk)
                    if count > max_bytes:
                        raise ValueError("Download exceeds single-file safety cap; use a scoped sample")
                    out.write(chunk)
                    digest.update(chunk)
        if count == 0:
            raise ValueError("Empty download")
        if target.suffix.lower() == ".zip" and not zipfile.is_zipfile(tmp_name):
            raise ValueError("Expected a ZIP, but received an invalid archive")
        os.replace(tmp_name, target)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return {"path": str(target.relative_to(ROOT)), "bytes": count,
            "sha256": digest.hexdigest(), "reused_existing": False}



def safe_extract_archive(archive: Path, output: Path, max_unpacked_bytes: int = 3 * 1024**3) -> int:
    """Extract a publisher ZIP without path escapes, symlinks, or excessive expansion."""
    if not zipfile.is_zipfile(archive):
        raise ValueError(f"Invalid nested dataset ZIP: {archive}")
    output.mkdir(parents=True, exist_ok=True)
    extracted = 0
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if len(members) > 30000:
            raise ValueError("Archive contains too many entries")
        if sum(info.file_size for info in members) > max_unpacked_bytes:
            raise ValueError("Unpacked dataset exceeds configured safety bound")
        for info in members:
            from pathlib import PurePosixPath
            p = PurePosixPath(info.filename)
            if p.is_absolute() or ".." in p.parts or not p.parts:
                raise ValueError(f"Dangerous member path in {archive}: {info.filename}")
            if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Archive contains a symbolic link")
            target = output.joinpath(*p.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                continue
            with zf.open(info) as read, target.open("wb") as write:
                shutil.copyfileobj(read, write, length=BUF)
            extracted += 1
    return extracted

def clone_git(dataset: dict, dest: Path) -> dict:
    if dest.exists() and (dest / ".git").exists():
        status = "reused_existing"
    elif dest.exists() and any(dest.iterdir()):
        raise ValueError(f"Refusing to overwrite nonempty non-repository folder: {dest}")
    else:
        if shutil.which("git") is None:
            raise RuntimeError("git executable is required for this source")
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", dataset["download_url"], str(dest)], check=True)
        status = "cloned"
    commit = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                            check=True, capture_output=True, text=True).stdout.strip()
    # Publisher repositories may include a nested data.zip rather than extracted data.
    # Extract only the two official Atticus dataset archives, preserving the originals.
    extracted = 0
    if dataset["id"] in ("cuad", "acord"):
        archives = sorted(dest.glob("*.zip"))
        for archive in archives:
            extracted += safe_extract_archive(archive, dest.parent / "extracted" / archive.stem)
    # Some large repos may use LFS. An installed git client does not guarantee
    # that all LFS-backed assets were downloaded; verify actual file content.
    return {"path": str(dest.relative_to(ROOT)), "git_commit": commit,
            "git_status": status, "extracted_files": extracted,
            "note": "Original publisher archives kept; verify Git LFS files and underlying dataset rights."}


def world_bank_fetch(dataset: dict, dest: Path, max_pages: int) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size and max_pages == 0:
        return {"path": str(dest.relative_to(ROOT)), "bytes": dest.stat().st_size,
                "sha256": hash_file(dest), "reused_existing": True,
                "note": "Check metadata to confirm full extraction; existing file was not overwritten"}
    fd, tmp_name = tempfile.mkstemp(prefix=".awards-", dir=str(dest.parent))
    count = 0
    pages = 0
    offset = 0
    limit = 1000
    final_page = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            while True:
                if max_pages and pages >= max_pages:
                    break
                url = dataset["download_url"] + f"&top={limit}&skip={offset}"
                payload = request_json(url)
                rows = payload.get("data")
                if not isinstance(rows, list):
                    raise ValueError("Unexpected World Bank JSON schema; expected a 'data' array")
                for row in rows:
                    out.write(json.dumps(row, ensure_ascii=True) + "\n")
                count += len(rows)
                pages += 1
                if len(rows) < limit:
                    final_page = True
                    break
                offset += limit
                time.sleep(0.15)
        if count == 0:
            raise ValueError("No procurement awards received")
        suffix = ".jsonl" if final_page else ".partial.jsonl"
        outpath = dest if final_page else dest.with_name(dest.stem + suffix)
        os.replace(tmp_name, outpath)
        meta = {
            "source": dataset["source_url"], "api": dataset["download_url"],
            "retrieved_at": timestamp(), "rows": count, "pages": pages,
            "complete": final_page, "note": "Source changes daily; snapshot is not guaranteed stable over a long pagination run."
        }
        (dest.parent / "acquisition_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return {"path": str(outpath.relative_to(ROOT)), "bytes": outpath.stat().st_size,
                "sha256": hash_file(outpath), "rows": count, "pages": pages,
                "complete": final_page}
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def figshare_fetch(dataset: dict, dest: Path) -> dict:
    metadata = request_json(dataset["download_url"])
    files = metadata.get("files") or []
    if not isinstance(files, list) or not files:
        raise ValueError("Figshare metadata has no downloadable files")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "figshare_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    outputs = []
    for f in files:
        link = f.get("download_url")
        name = Path(f.get("name", "")).name
        if not name or not link:
            raise ValueError("Incomplete Figshare file metadata")
        receipt = download_binary(link, dest / name)
        expected = f.get("size")
        if expected is not None and int(expected) != receipt["bytes"]:
            raise ValueError(f"Figshare size mismatch on {name}")
        outputs.append(receipt)
    return {"files": outputs, "file_count": len(outputs),
            "api_metadata_path": str((dest / "figshare_metadata.json").relative_to(ROOT))}



def ted_fetch(dataset: dict, dest: Path, query: str, max_pages: int) -> dict:
    """Fetch a bounded published-notice set. The default is intentionally NOT an EU-wide bulk crawl."""
    if max_pages <= 0 or max_pages > 100:
        raise ValueError("--ted-pages must be 1 to 100; use a narrow query for complete exports")
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "query": query,
        "fields": ["publication-number", "notice-title", "buyer-name", "buyer-country",
                   "publication-date", "classification-cpv", "notice-type"],
        "scope": "ALL", "limit": 100, "paginationMode": "PAGE_NUMBER",
    }
    fd, tmp_name = tempfile.mkstemp(prefix=".ted-", dir=str(dest.parent))
    count = 0
    pages = 0
    complete = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            for page in range(1, max_pages + 1):
                body = json.dumps({**payload, "page": page}).encode("utf-8")
                req = urllib.request.Request(
                    dataset["download_url"], data=body,
                    headers={"User-Agent": USER_AGENT, "Content-Type": "application/json",
                             "Accept": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=120) as response:
                    data = json.load(response)
                items = data.get("notices", data.get("results", data.get("data")))
                if not isinstance(items, list):
                    raise ValueError("Unrecognised TED API response; check current v3 documentation for field names")
                for row in items:
                    out.write(json.dumps(row, ensure_ascii=True) + "\n")
                count += len(items)
                pages += 1
                if len(items) < 100:
                    complete = True
                    break
                time.sleep(0.25)
        if count == 0:
            raise ValueError("No TED notices matched the query")
        outpath = dest if complete else dest.with_name("notices.partial.jsonl")
        os.replace(tmp_name, outpath)
        (dest.parent / "acquisition_metadata.json").write_text(
            json.dumps({"retrieved_at": timestamp(), "api": dataset["download_url"],
                        "query": query, "pages": pages, "records": count,
                        "query_exhausted": complete,
                        "note": "Notice titles can be multilingual; historical amendments and notices need deduplication."},
                       indent=2), encoding="utf-8")
        return {"path": str(outpath.relative_to(ROOT)), "bytes": outpath.stat().st_size,
                "sha256": hash_file(outpath), "rows": count, "pages": pages,
                "complete": complete, "query": query}
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

def m5_fetch(dest: Path, acknowledged: bool) -> dict:
    if not acknowledged:
        raise PermissionError("M5 needs --ack-m5-noncommercial AFTER you personally accept the Kaggle terms")
    if not shutil.which("kaggle"):
        raise RuntimeError("Install Kaggle CLI and authenticate, then accept M5 rules on the Kaggle website")
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["kaggle", "competitions", "download", "-c", "m5-forecasting-accuracy", "-p", str(dest)]
    subprocess.run(cmd, check=True)
    files = sorted(p for p in dest.rglob("*") if p.is_file())
    if not files:
        raise RuntimeError("Kaggle CLI returned without a dataset file")
    return {"path": str(dest.relative_to(ROOT)), "files": [
        {"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size,
         "sha256": hash_file(p)} for p in files],
        "academic_only": True, "not_for_commercial_demo": True}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="core", choices=["core", "academic", "optional", "all"])
    ap.add_argument("--dataset", nargs="+", help="Specific dataset IDs instead of profile")
    ap.add_argument("--list", action="store_true", help="Show catalog with current download state")
    ap.add_argument("--dry-run", action="store_true", help="Print plan only; make no network requests")
    ap.add_argument("--ack-m5-noncommercial", action="store_true", help="Confirm you accepted the M5 Kaggle rules and will not use its data commercially")
    ap.add_argument("--ack-sharealike", action="store_true", help="Confirm you reviewed BDG2 ShareAlike terms before downloading")
    ap.add_argument("--max-worldbank-pages", type=int, default=0, help="0 means all pages; >0 produces partial data with a .partial.jsonl suffix")
    ap.add_argument("--ted-query", default='FT~"industrial pumps" AND PD>=20240101 SORT BY publication-date DESC', help="TED v3 expert-search query; keep scope bounded")
    ap.add_argument("--ted-pages", type=int, default=3, help="Maximum TED result pages (100 notices per page); default 3")
    ns = ap.parse_args()
    if ns.max_worldbank_pages < 0:
        ap.error("--max-worldbank-pages cannot be negative")
    catalog = load_catalog()
    by_id = {d["id"]: d for d in catalog}
    if ns.list:
        for d in catalog:
            path = ROOT / d["destination"]
            print(f"{d['id']:24} {d['profile']:9} {d['method']:19} {'PRESENT' if path.exists() else 'NOT DOWNLOADED'}")
        return 0
    if ns.dataset:
        unknown = set(ns.dataset) - set(by_id)
        if unknown:
            ap.error(f"Unknown dataset(s): {', '.join(sorted(unknown))}")
        selected = [by_id[x] for x in ns.dataset]
    else:
        selected = [d for d in catalog if ns.profile == "all" or d["profile"] == ns.profile]
    print(f"Plan: {len(selected)} source(s). Destination: {ROOT}; network required for real data.")
    errors = 0
    for d in selected:
        print(f"\n[{d['id']}] {d['name']}\n  method: {d['method']}\n  licence: {d['commercial_rights']}")
        if ns.dry_run:
            print(f"  DRY RUN: {d['source_url']} -> {d['destination']}")
            continue
        method = d["method"]
        path = ROOT / d["destination"]
        try:
            if method == "http_zip":
                result = download_binary(d["download_url"], path)
            elif method == "git":
                result = clone_git(d, path)
            elif method == "git_restricted":
                if not ns.ack_sharealike:
                    raise PermissionError("BDG2 needs --ack-sharealike after reviewing licence requirements")
                result = clone_git(d, path)
            elif method == "world_bank_api":
                result = world_bank_fetch(d, path, ns.max_worldbank_pages)
            elif method == "ted_api":
                result = ted_fetch(d, path, ns.ted_query, ns.ted_pages)
            elif method == "figshare_api":
                result = figshare_fetch(d, path)
            elif method == "kaggle_competition":
                result = m5_fetch(path, ns.ack_m5_noncommercial)
            else:
                print("  MANUAL: review source terms and download a controlled subset from the official page:")
                print("  " + d["source_url"])
                print("  Save to " + d["destination"])
                record(d, "manual_required", reason=d["notes"])
                continue
            record(d, "downloaded" if not result.get("reused_existing") else "reused_existing", **result)
            print("  OK: " + str(result.get("path", result.get("file_count", "downloaded"))))
            if result.get("complete") is False:
                print("  PARTIAL SNAPSHOT: raise --max-worldbank-pages or use 0 for all pages")
        except Exception as exc:
            errors += 1
            record(d, "failed", error=f"{type(exc).__name__}: {exc}")
            print(f"  FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"\nFinished: {len(selected)} sources attempted; {errors} failed. Manual-only sources need user action.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
