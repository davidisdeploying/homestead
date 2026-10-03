"""Field extraction shared by the Zillow and Redfin alert parsers.

Both templates are marketing HTML whose CSS classes change without notice, so nothing here
keys off class names or exact wording. It keys off *data shapes* — a dollar amount, a
bed/bath/area run, a `Street, City, ST ZIP` line — which are what the templates actually
promise a reader.

Nothing in this module invents a value. A field the alert did not state comes back None,
because `None` reaches the UI as "the alert did not say" while `""` or `0` reads as "the
alert said this".
"""
import re

# "9 Fictional Ln, Garland, TX 75040" and the ZIP-less Zillow variant
# "4102 Cottonwood Bend, Richardson, TX".
ADDRESS_LINE = re.compile(
    r"^\s*(?P<street>[0-9][^,]{3,80}?)\s*,\s*(?P<city>[A-Za-z][A-Za-z .'-]{1,40}?)\s*,\s*"
    r"(?P<state>[A-Z]{2})(?:\s+(?P<postal>\d{5})(?:-\d{4})?)?\s*$"
)

MONEY = re.compile(r"\$\s?([\d,]+)")


def money(value):
    """First dollar amount in `value` as an int, or None."""
    match = MONEY.search(str(value or ""))
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def number(value):
    """A bare number (possibly with thousands separators or a decimal) as int/float."""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    return float(text) if "." in text else int(text)


def parse_address_line(line):
    """Split a `Street, City, ST [ZIP]` line, or return None if it is not one."""
    match = ADDRESS_LINE.match(str(line or ""))
    if not match:
        return None
    parts = match.groupdict()
    return {
        "address": parts["street"].strip(),
        "city": parts["city"].strip(),
        "state": parts["state"],
        "postal_code": parts["postal"],
    }


def find_address(lines, start=0, limit=8):
    """First parseable address line at or after `start`, with its index."""
    for offset, line in enumerate(lines[start:start + limit]):
        parsed = parse_address_line(line)
        if parsed:
            return parsed, start + offset
    return None, None


def postal_from_subject(subject, street):
    """Recover a ZIP from the subject when the card omitted it.

    Zillow's card prints `Street, City, TX` while its subject prints
    `Street City, TX 75044`. The ZIP is only accepted when the subject is talking about
    the same street, so a ZIP belonging to a different property can never be attached.
    """
    subject = str(subject or "")
    street = str(street or "").strip()
    if not street or street.lower() not in subject.lower():
        return None
    match = re.search(re.escape(street) + r"[^.]*?\b(\d{5})\b", subject, re.I)
    return match.group(1) if match else None


# A line holding nothing but a separator. Marketing email is built from tables, and both
# Zillow and Redfin put the separators between bed/bath/area in their own <td>, so the
# real Zillow alert flattens to:
#
#     4 bd / | / 2 ba / | / 1,376 sqft
#
# on five lines rather than one. Gmail's rendered innerText joins them, which is why a
# browser-side check of the same regex passed while the importer parsed nothing.
_SEPARATOR_ONLY = re.compile(r"^[|·•]+$")


def merge_separator_lines(lines):
    """Re-join fields that a table layout split across lines around a separator."""
    merged = []
    join_next = False
    for line in lines:
        separator = bool(_SEPARATOR_ONLY.match(line))
        if (join_next or separator) and merged:
            merged[-1] = f"{merged[-1]} {line}"
        else:
            merged.append(line)
        join_next = separator
    return merged


def text_lines(decoded):
    """Readable lines from a decoded Gmail message, HTML preferred over plain text."""
    from .mime import strip_html

    html = (decoded or {}).get("html") or ""
    plain = (decoded or {}).get("plain") or ""
    source = strip_html(html) if html.strip() else plain
    return merge_separator_lines(
        [line.strip() for line in source.splitlines() if line.strip()]
    )


def cut_at(lines, markers):
    """Truncate `lines` at the first line that begins a marker section.

    This is how recommendation blocks are excluded. Without it a single Redfin alert
    imports the one home David's search matched plus every "nearby similar home" the
    template advertises underneath it.
    """
    lowered = [line.lower() for line in lines]
    for index, line in enumerate(lowered):
        for marker in markers:
            if line.startswith(marker):
                return lines[:index]
    return lines
