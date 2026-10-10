"""Private, hash-bound EPUB presentation for Homestead learning sections."""
from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import os
import posixpath
import re
import sqlite3
import zipfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

READER_DB = Path(os.environ.get("HOMESTEAD_READER_DB", "/var/lib/homestead/learning/reader.sqlite3"))
EPUB_ROOT = Path(os.environ.get("HOMESTEAD_EPUB_ROOT", "/var/lib/homestead/learning/epubs")).resolve()
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd", "figcaption", "blockquote", "pre"}
ALLOWED_TAGS = {
    "div", "section", "article", "aside", "header", "footer", "figure", "figcaption",
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
    "strong", "b", "em", "i", "small", "mark", "span", "sup", "sub", "blockquote",
    "pre", "code", "br", "hr", "img", "a",
}
DROP_TAGS = {"script", "style", "nav", "noscript", "iframe", "object", "embed", "form", "input", "button", "audio", "video", "source", "link"}
IMAGE_MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
STABLE_ID_RE = re.compile(r"[a-z0-9][a-z0-9:_-]{2,239}\Z")
TOKEN_RE = re.compile(r"[a-f0-9]{32}\Z")


class ReaderUnavailable(Exception):
    pass


@contextmanager
def connect(path=READER_DB):
    """Open the reader index and always close it.

    Same defect as `listing_db.connect` had: `with connect(...) as conn:` relies on
    `sqlite3.Connection.__exit__`, which commits but does not close, so every reader
    section and image request leaked a connection. Reads only, but the leak is identical.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _normalize(value):
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def safe_member(base, href):
    href = (href or "").split("#", 1)[0].split("?", 1)[0]
    member = posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    if not href or member.startswith("/") or member == ".." or member.startswith("../") or "\\" in member:
        raise ReaderUnavailable("unsafe EPUB resource path")
    return member


def validate_zip_names(names):
    for name in names:
        normalized = posixpath.normpath(name)
        if name.startswith("/") or normalized == ".." or normalized.startswith("../") or "\\" in name:
            raise ReaderUnavailable("unsafe EPUB member path")


@lru_cache(maxsize=16)
def _verify(path_text, expected_hash, size, mtime_ns):
    path = Path(path_text)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if not expected_hash or digest.hexdigest() != expected_hash:
        raise ReaderUnavailable("EPUB identity check failed")
    with zipfile.ZipFile(path) as epub:
        validate_zip_names(epub.namelist())
        if epub.testzip() is not None:
            raise ReaderUnavailable("EPUB integrity check failed")
    return path


def verify_epub(path_text, expected_hash, root=EPUB_ROOT):
    path = Path(path_text).resolve()
    if not _within(path, Path(root).resolve()) or not path.is_file() or path.suffix.lower() != ".epub":
        raise ReaderUnavailable("EPUB source is unavailable")
    stat = path.stat()
    return _verify(str(path), expected_hash, stat.st_size, stat.st_mtime_ns)


def markdown_candidates(content):
    candidates = []
    for index, block in enumerate(re.split(r"\n\s*\n", content or "")):
        value = block.strip()
        if not value or re.fullmatch(r"-+", value) or (index == 0 and value.startswith("# ")):
            continue
        value = re.sub(r"^#{1,6}\s+", "", value)
        value = re.sub(r"(?m)^\s*(?:[-*]|\d+\.)\s+", "", value)
        value = value.replace("**", "").replace("`", "").replace("*", "")
        if value.startswith("[Image:") and value.endswith("]"):
            value = value[7:-1]
        value = _normalize(value)
        if len(value) >= 24:
            candidates.append(value)
        if len(candidates) >= 20:
            break
    return candidates


def element_path(root, target):
    parents = {child: node for node in root.iter() for child in node}
    parts, node = [], target
    while node is not root:
        owner = parents.get(node)
        if owner is None:
            raise ReaderUnavailable("EPUB locator could not be created")
        parts.append(str(list(owner).index(node)))
        node = owner
    return "/".join(reversed(parts))


def find_boundary(root, content, after_index=-1):
    ordered = list(root.iter())
    indexes = {element: index for index, element in enumerate(ordered)}
    parents = {child: node for node in ordered for child in node}
    def in_navigation(element):
        node = element
        while node is not None:
            if _local(node.tag) == "nav": return True
            node = parents.get(node)
        return False
    elements = [element for element in ordered if _local(element.tag) in BLOCK_TAGS and not in_navigation(element)]
    for candidate in markdown_candidates(content):
        probe = candidate[:220]
        matches = []
        for element in elements:
            if indexes[element] <= after_index:
                continue
            value = _normalize(" ".join(element.itertext()))
            if value and (value.startswith(probe) or probe.startswith(value[:220])):
                matches.append((len(value), indexes[element], element))
        if matches:
            return min(matches, key=lambda item: (item[0], item[1]))[2]
    raise ReaderUnavailable("EPUB section boundary could not be located")


def _sanitize_attrs(element, tag, source_item, stable_id, names, assets):
    attrs = {}
    for raw_key, value in element.attrib.items():
        key = _local(raw_key)
        if key.startswith("on") or key == "style":
            continue
        if key in {"id", "class"}:
            cleaned = re.sub(r"[^A-Za-z0-9_:. -]", "", value)[:240]
            if cleaned:
                attrs[key] = cleaned
        elif key in {"alt", "title", "aria-label", "aria-describedby", "scope"}:
            attrs[key] = value[:1000]
        elif key in {"width", "height", "colspan", "rowspan", "start"} and re.fullmatch(r"\d{1,5}", value or ""):
            attrs[key] = value
    if tag == "img":
        member = safe_member(source_item, element.attrib.get("src", ""))
        extension = Path(member).suffix.lower()
        if member not in names or extension not in IMAGE_MIMES:
            raise ReaderUnavailable("EPUB image resource is missing or not permitted")
        token = hashlib.sha256(member.encode()).hexdigest()[:32]
        assets[token] = (member, IMAGE_MIMES[extension])
        attrs["src"] = f"/api/learning/sections/{quote(stable_id, safe='')}/assets/{token}"
        attrs["loading"] = "eager"
        attrs["decoding"] = "async"
    elif tag == "a":
        href = element.attrib.get("href", "")
        if href.startswith("#") and re.fullmatch(r"#[A-Za-z0-9_:.-]+", href):
            attrs["href"] = href
    return attrs


def clone_range(root, source_item, stable_id, names, start_element, end_element=None):
    ordered = list(root.iter())
    indexes = {element: index for index, element in enumerate(ordered)}
    subtree_end = {}
    def record_end(element):
        end = indexes[element]
        for child in element:
            end = max(end, record_end(child))
        subtree_end[element] = end
        return end
    record_end(root)
    start = indexes[start_element]
    end = indexes[end_element] if end_element is not None else len(ordered)
    if end <= start:
        raise ReaderUnavailable("EPUB section range is invalid")
    assets = {}
    def clone(element):
        if subtree_end[element] < start or indexes[element] >= end:
            return None
        source_tag = _local(element.tag)
        if source_tag in DROP_TAGS:
            return None
        tag = source_tag if source_tag in ALLOWED_TAGS else "div"
        copied = ET.Element(tag, _sanitize_attrs(element, tag, source_item, stable_id, names, assets))
        if start <= indexes[element] < end:
            copied.text = element.text
        for child in element:
            child_copy = clone(child)
            if child_copy is not None:
                if subtree_end[child] >= start and subtree_end[child] < end:
                    child_copy.tail = child.tail
                copied.append(child_copy)
        return copied
    return clone(root), assets


def inner_html(element):
    return html.escape(element.text or "") + "".join(ET.tostring(child, encoding="unicode", method="html") for child in element)


def reader_section(stable_id, db_path=READER_DB, epub_root=EPUB_ROOT):
    if not STABLE_ID_RE.fullmatch(stable_id):
        return None
    try:
        with connect(db_path) as conn:
            row = conn.execute("SELECT * FROM section_mappings WHERE stable_id=?", (stable_id,)).fetchone()
        if not row:
            return None
        payload = {"stable_id": row["stable_id"], "title": row["title"], "book_title": row["book_title"],
                   "reader_format": row["reader_format"], "content": row["markdown_content"],
                   "html": row["sanitized_html"], "locator": row["start_locator"],
                   "end_locator": row["end_locator"], "fallback_reason": row["fallback_reason"]}
        if row["reader_format"] == "epub":
            try:
                verify_epub(row["epub_path"], row["epub_sha256"], epub_root)
            except (ReaderUnavailable, OSError, zipfile.BadZipFile):
                payload.update(reader_format="markdown", html=None, fallback_reason="EPUB source failed its integrity check")
        return payload
    except (OSError, sqlite3.Error):
        return None


def reader_asset(stable_id, token, db_path=READER_DB, epub_root=EPUB_ROOT):
    if not STABLE_ID_RE.fullmatch(stable_id) or not TOKEN_RE.fullmatch(token):
        raise ReaderUnavailable("asset not found")
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT a.member_path,a.mime_type,s.epub_path,s.epub_sha256 FROM reader_assets a "
            "JOIN section_mappings s ON s.stable_id=a.stable_id WHERE a.stable_id=? AND a.token=? AND s.reader_format='epub'",
            (stable_id, token),
        ).fetchone()
    if not row:
        raise ReaderUnavailable("asset not found")
    path = verify_epub(row["epub_path"], row["epub_sha256"], epub_root)
    with zipfile.ZipFile(path) as epub:
        names = epub.namelist(); validate_zip_names(names)
        if row["member_path"] not in names or Path(row["member_path"]).suffix.lower() not in IMAGE_MIMES:
            raise ReaderUnavailable("asset not found")
        data = epub.read(row["member_path"])
    if len(data) > 20 * 1024 * 1024:
        raise ReaderUnavailable("asset too large")
    return data, row["mime_type"]


def create_schema(conn):
    conn.executescript("""
    PRAGMA user_version=1;
    CREATE TABLE IF NOT EXISTS section_mappings(
      stable_id TEXT PRIMARY KEY, book_id TEXT NOT NULL, title TEXT NOT NULL, book_title TEXT NOT NULL,
      reader_format TEXT NOT NULL CHECK(reader_format IN ('epub','markdown')), markdown_content TEXT NOT NULL,
      epub_sha256 TEXT, epub_path TEXT, source_item TEXT, start_locator TEXT, end_locator TEXT,
      sanitized_html TEXT, fallback_reason TEXT, mapped_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS reader_assets(
      stable_id TEXT NOT NULL REFERENCES section_mappings(stable_id) ON DELETE CASCADE,
      token TEXT NOT NULL, member_path TEXT NOT NULL, mime_type TEXT NOT NULL,
      PRIMARY KEY(stable_id,token)
    );
    CREATE INDEX IF NOT EXISTS idx_reader_book ON section_mappings(book_id,reader_format);
    """)
