#!/usr/bin/env python3
"""Build Homestead's additive section-to-EPUB presentation index."""
from __future__ import annotations
import argparse, hashlib, json, shutil, sqlite3, sys, zipfile
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reader_library import (ReaderUnavailable, clone_range, create_schema, element_path,
                            find_boundary, inner_html, validate_zip_names)

EPUB_BOOKS = {
    "nolo-essential-guide-2023",
    "home-buying-kit-dummies-2025",
    "first-time-home-buyer-2021",
}
FLEMING = "fleming-buying-financing-2023"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def within(path, root):
    try: path.relative_to(root); return True
    except ValueError: return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-db", required=True, type=Path)
    parser.add_argument("--conversion-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--runtime-epub-root", required=True, type=Path)
    parser.add_argument("--recorded-epub-root", type=Path, help="final private runtime root recorded in the mapping DB")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-complete-epub", action="store_true")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    args.runtime_epub_root.mkdir(parents=True, exist_ok=True)
    recorded_root = (args.recorded_epub_root or args.runtime_epub_root).resolve()
    if args.output.exists(): args.output.unlink()
    source = sqlite3.connect(f"file:{args.knowledge_db}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    output = sqlite3.connect(args.output)
    create_schema(output)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    coverage = {}

    for book in source.execute("SELECT * FROM books WHERE slug IN (?,?,?,?) ORDER BY slug", (*sorted(EPUB_BOOKS), FLEMING)):
        slug = book["slug"]
        sections = source.execute("SELECT * FROM sections WHERE book_id=? ORDER BY position", (book["id"],)).fetchall()
        stats = {"total": len(sections), "epub": 0, "markdown": 0, "failures": []}
        coverage[slug] = stats
        if slug == FLEMING:
            for section in sections:
                output.execute("INSERT INTO section_mappings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    section["section_id"], slug, section["title"], book["title"], "markdown", section["content"],
                    None, None, None, None, None, None, "OCR/PDF source; no original EPUB exists", now))
                stats["markdown"] += 1
            continue

        report_path = args.conversion_root / slug / "conversion-report.json"
        report = json.loads(report_path.read_text())
        canonical = Path(report["source"]).resolve()
        expected = report["source_sha256"]
        book_hash = book["source_epub_sha256"]
        if not within(canonical, source_root) or canonical.suffix.lower() != ".epub":
            raise SystemExit(f"{slug}: source escaped approved root")
        actual = sha256(canonical)
        if actual != expected or actual != book_hash:
            raise SystemExit(f"{slug}: immutable source hash mismatch")
        runtime = (args.runtime_epub_root / f"{actual}.epub").resolve()
        if not within(runtime, args.runtime_epub_root.resolve()): raise SystemExit("unsafe runtime path")
        shutil.copyfile(canonical, runtime)
        if sha256(runtime) != actual: raise SystemExit(f"{slug}: runtime copy verification failed")
        recorded_runtime = recorded_root / runtime.name

        report_by_position = {item["position"]: item for item in report["sections"]}
        if len(report_by_position) != len(sections): raise SystemExit(f"{slug}: report/KB section count mismatch")
        groups = {}
        for section in sections:
            item = report_by_position.get(section["position"])
            if not item or item["sha256"] != section["sha256"]:
                raise SystemExit(f"{slug}:{section['section_id']}: report/KB identity mismatch")
            groups.setdefault(item["source_item"], []).append((section, item))

        with zipfile.ZipFile(runtime) as epub:
            names = set(epub.namelist()); validate_zip_names(names)
            if epub.testzip() is not None: raise SystemExit(f"{slug}: malformed EPUB")
            for source_item, group in groups.items():
                try:
                    if source_item not in names: raise ReaderUnavailable("spine item missing")
                    root = ET.fromstring(epub.read(source_item))
                    body = next((node for node in root.iter() if node.tag.rsplit("}",1)[-1].lower()=="body"), root)
                    ordered = list(body.iter())
                    boundaries = []
                    if len(group) > 1:
                        last = -1
                        for section, _item in group:
                            boundary = find_boundary(body, section["content"], last)
                            last = ordered.index(boundary)
                            boundaries.append(boundary)
                    else:
                        boundaries = [body]
                    for index, (section, item) in enumerate(group):
                        start = boundaries[index]
                        end = boundaries[index + 1] if index + 1 < len(boundaries) else None
                        cloned, assets = clone_range(body, source_item, section["section_id"], names, start, end)
                        if cloned is None: raise ReaderUnavailable("empty EPUB section")
                        rendered = '<div class="epub-reader-content">' + inner_html(cloned) + '</div>'
                        if not rendered.strip(): raise ReaderUnavailable("empty EPUB section")
                        start_locator = f"{source_item}#path={element_path(body,start)}"
                        end_locator = f"{source_item}#path={element_path(body,end)}" if end is not None else None
                        output.execute("INSERT INTO section_mappings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                            section["section_id"], slug, section["title"], book["title"], "epub", section["content"],
                            actual, str(recorded_runtime), source_item, start_locator, end_locator, rendered, None, now))
                        for token, (member, mime) in assets.items():
                            output.execute("INSERT INTO reader_assets VALUES(?,?,?,?)", (section["section_id"], token, member, mime))
                        stats["epub"] += 1
                except (ReaderUnavailable, ET.ParseError, KeyError, ValueError) as exc:
                    for section, item in group:
                        if output.execute("SELECT 1 FROM section_mappings WHERE stable_id=?", (section["section_id"],)).fetchone():
                            continue
                        reason = str(exc)[:240]
                        output.execute("INSERT INTO section_mappings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                            section["section_id"], slug, section["title"], book["title"], "markdown", section["content"],
                            actual, str(recorded_runtime), source_item, None, None, None, reason, now))
                        stats["markdown"] += 1; stats["failures"].append({"stable_id": section["section_id"], "reason": reason})
    output.commit()
    output.execute("PRAGMA foreign_key_check")
    integrity = output.execute("PRAGMA integrity_check").fetchone()[0]
    output.close(); source.close()
    result = {"schema_version": 1, "integrity": integrity, "coverage": coverage}
    print(json.dumps(result, indent=2))
    if integrity != "ok": return 2
    if args.require_complete_epub and any(coverage[slug]["markdown"] for slug in EPUB_BOOKS): return 3
    return 0

if __name__ == "__main__": raise SystemExit(main())
