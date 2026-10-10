"""Gmail message decoding, shared by every source adapter.

This layer is deliberately template-independent: it knows about base64url, nested
multipart trees, charsets, and HTML entities -- all RFC/API facts -- and knows nothing
about Zillow or Redfin. Adapters receive decoded text and headers and do the source-
specific work. Getting this wrong is the classic silent-corruption bug: Prospect fused
company and location for weeks because one `&middot;` entity went undecoded.
"""
import base64
import html
import re


def decode_base64url(value):
    """Decode Gmail's base64url body data, tolerating missing padding."""
    if not value:
        return b""
    text = str(value).replace("-", "+").replace("_", "/")
    padding = (-len(text)) % 4
    try:
        return base64.b64decode(text + "=" * padding)
    except (ValueError, TypeError):
        return b""


def headers(payload):
    """Lowercase header-name -> value map for one message payload."""
    result = {}
    for header in (payload or {}).get("headers") or []:
        name = str(header.get("name", "")).lower()
        if name and name not in result:
            result[name] = str(header.get("value", ""))
    return result


def _charset(part):
    mime_headers = headers(part)
    match = re.search(r'charset="?([A-Za-z0-9_.:+-]+)"?', mime_headers.get("content-type", ""))
    return match.group(1) if match else "utf-8"


def collect_parts(payload, output=None):
    """Walk the full MIME tree and gather decoded text/html and text/plain bodies.

    Real alert mail nests: multipart/mixed -> multipart/alternative -> text/html. A
    non-recursive reader silently sees an empty body and reports "nothing to import".
    """
    if output is None:
        output = {"html": [], "plain": []}
    if not payload:
        return output
    mime_type = str(payload.get("mimeType", "")).lower()
    raw = decode_base64url((payload.get("body") or {}).get("data"))
    if raw:
        try:
            text = raw.decode(_charset(payload), errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        if mime_type == "text/html":
            output["html"].append(text)
        elif mime_type == "text/plain":
            output["plain"].append(text)
    for child in payload.get("parts") or []:
        collect_parts(child, output)
    return output


def decode_entities(value):
    """Full named + numeric entity decoding via the stdlib table.

    `html.unescape` is used rather than a hand-written replacement map precisely because
    hand-written maps are always missing the one entity that matters.
    """
    return html.unescape(str(value or ""))


def strip_html(value):
    """Flatten HTML to readable lines, preserving block boundaries."""
    text = str(value or "")
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<(br|/p|/div|/li|/tr|/td|/h[1-6]|/table)\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = decode_entities(text).replace("\r", "")
    lines = (" ".join(line.split()) for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def message_text(message):
    """Return {html, plain, headers} for a full-format Gmail message."""
    payload = (message or {}).get("payload") or {}
    parts = collect_parts(payload)
    html_body = "\n".join(parts["html"])
    plain_body = "\n".join(parts["plain"]) or strip_html(html_body)
    return {"html": html_body, "plain": plain_body, "headers": headers(payload)}


def sender_address(value):
    """Extract the bare address from a From header, lowercased."""
    match = re.search(r"<([^<>@\s]+@[^<>@\s]+)>", str(value or ""))
    if match:
        return match.group(1).lower()
    match = re.search(r"([^<>@\s]+@[^<>@\s]+)", str(value or ""))
    return match.group(1).lower() if match else ""


def received_at(message):
    """Gmail internalDate (epoch ms) as an ISO-8601 UTC string."""
    raw = (message or {}).get("internalDate")
    if raw is None:
        return None
    try:
        from datetime import datetime, timezone
        return (datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
                .replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    except (TypeError, ValueError, OSError):
        return None
