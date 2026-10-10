#!/usr/bin/env python3
"""Export a bounded Homestead learning payload from the compiled knowledge base.

The app receives focused excerpts, never whole chapters. Published books remain
distinct from Homestead-authored gap dossiers, and OCR-derived text carries its
fidelity warning into the UI.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
from pathlib import Path

MAX_EXCERPT = 1800
MAX_BOOK_READINGS = 3
TRACK_NAMES = {
    "20-19": "The purchase contract",
    "40-11": "Financing approval",
}

JOURNEY_CURRICULUM = [
    {
        "code": "JOURNEY-PREPARE", "title": "Prepare", "when": "Before you shop",
        "lessons": [
            ("01", "Decide whether buying fits your life",
             "Separate the desire to own from the financial and lifestyle case for owning now.",
             "Read this before treating a purchase as inevitable. Name what would make waiting the better decision.",
             "What would have to be true for buying now to beat renting for the household?",
             [("first-time-home-buyer-2021", "first-time-home-buyer-2021:012-chapter-one", "IS BUYING A HOUSE A GOOD INVESTMENT?", "Is buying a house a good investment?"),
              ("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:007-deciding-whether-to-buy", None, "Deciding whether to buy")]),
            ("02", "Define the home you actually need",
             "Turn location, space, commute, four dogs, and future plans into explicit tradeoffs before listings create urgency.",
             "Build the needs list before touring. Distinguish must-haves, strong preferences, and things you can change later.",
             "Which three constraints are truly non-negotiable, and which attractive features could distract you?",
             [("nolo-essential-guide-2023", "nolo-essential-guide-2023:012-chapter-2what-do-you-want-figuring-out-your-homebuying-needs", None, "Figuring out your homebuying needs"),
              ("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:018-where-and-what-to-buy-part-1-of-3", None, "Where and what to buy")]),
            ("03", "Set the real budget and cash reserves",
             "Price the whole purchase: down payment, closing costs, repairs, moving, and the monthly payment after taxes and insurance.",
             "The lender's maximum is not your household maximum. Preserve a separate closing reserve and post-closing cushion.",
             "What is your walk-away monthly payment, and what cash must remain untouched after closing?",
             [("nolo-essential-guide-2023", "nolo-essential-guide-2023:013-chapter-3does-this-mean-i-have-to-balance-my-checkbook-figuring-out-what", None, "Figuring out what you can afford"),
              ("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:008-getting-your-financial-house-in-order", None, "Getting your financial house in order")]),
            ("04", "Prepare credit, income, and documents",
             "Clean up credit early and assemble the records underwriting will ask for before a deadline depends on them.",
             "Do this months before preapproval. For non-W-2 income, expect a longer evidence trail.",
             "What could delay or reduce approval even if the down payment is ready?",
             [("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:013-understanding-and-improving-your-credit-score", None, "Understanding and improving your credit score"),
              ("first-time-home-buyer-2021", "first-time-home-buyer-2021:017-chapter-five", "PREPARING TO PURCHASE", "Preparing to purchase")]),
            ("05", "Choose lenders and agents without giving up leverage",
             "Interview the people who get paid when the deal closes, compare their economics, and keep the ability to walk away.",
             "Use the 2025 team guidance for the post-August-2024 compensation environment; older books can be stale on buyer-agent fees.",
             "How will each professional be paid, what conflicts do they have, and what evidence proves their recommendation?",
             [("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:021-assembling-an-all-star-real-estate-team-part-1-of-2", None, "Assembling your real-estate team"),
              ("first-time-home-buyer-2021", "first-time-home-buyer-2021:019-chapter-seven", "CHOOSING THE BEST LENDER", "Choosing a lender")]),
        ],
    },
    {
        "code": "JOURNEY-SEARCH", "title": "Search", "when": "From preapproval to the right house",
        "lessons": [
            ("01", "Read the market before the listings",
             "Understand what moves prices and how asking price, market value, and affordability differ.",
             "Use market context to set expectations, never as permission to exceed the household ceiling.",
             "Which facts would show that a listing is overpriced, and which are merely market noise?",
             [("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:011-why-home-prices-rise-and-fall", None, "Why home prices rise and fall"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:015-chapter-4stepping-out-whats-on-the-market-and-at-what-price", None, "What's on the market and at what price")]),
            ("02", "Turn the needs list into a search strategy",
             "Search broadly enough to learn, then narrow by property, neighborhood, commute, taxes, and recurring constraints.",
             "Record every tour while memory is fresh. The goal is a comparable decision record, not a gallery of favorites.",
             "What evidence will you record after every tour so the fifth house can be compared with the first?",
             [("first-time-home-buyer-2021", "first-time-home-buyer-2021:022-chapter-nine", "LISTINGS, VIEWINGS, AND STARTING YOUR SEARCH", "Listings, viewings, and starting your search"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:021-chapter-8i-love-it-its-perfect-looking-for-the-right-house-part-1-of-2", None, "Looking for the right house")]),
            ("03", "Evaluate location, condition, and resale together",
             "A house is the structure, the lot, the surrounding obligations, and the future exit—not just the rooms you tour.",
             "Look past finishes. In North Texas, drainage, slab, fence, tax district, insurance, and resale constraints can dominate.",
             "Which expensive or irreversible property facts could enthusiasm cause you to overlook?",
             [("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:019-where-and-what-to-buy-part-2-of-3", None, "Evaluating where and what to buy"),
              ("first-time-home-buyer-2021", "first-time-home-buyer-2021:013-chapter-two", "UNDERSTANDING EXIT OPTIONS", "Understanding exit options")]),
        ],
    },
    {
        "code": "JOURNEY-OFFER", "title": "Offer & option", "when": "From price decision through inspection",
        "lessons": [
            ("01", "Estimate value and set a walk-away price",
             "Use comparable evidence and the property's real defects to decide value before negotiation begins.",
             "Write the ceiling down first. A rejected offer is cheaper than winning at a price you regret.",
             "What evidence supports your price, and what fact would make you walk away rather than bid higher?",
             [("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:023-whats-it-worth-part-1-of-2", None, "What's it worth?"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:015-chapter-4stepping-out-whats-on-the-market-and-at-what-price", "comparable", "Prices and comparable homes")]),
            ("02", "Write an offer that protects you",
             "The offer becomes the contract. Price matters, but contingencies, deadlines, fees, included property, and notice details carry rights.",
             "Read this before the agent drafts anything. Then use the TREC 20-19 track for the Texas clauses themselves.",
             "Which protections would you refuse to waive even if the seller prefers a cleaner offer?",
             [("first-time-home-buyer-2021", "first-time-home-buyer-2021:023-chapter-ten", "MAKING AN OFFER", "Making an offer"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:025-chapter-10show-them-the-money-from-offer-to-purchase-agreement-part-1-of", None, "From offer to purchase agreement")]),
            ("03", "Negotiate price, timing, and concessions",
             "Treat every term as part of one trade: price, repairs, closing date, financing costs, included property, and certainty.",
             "Do not negotiate against yourself. Ask what the seller values before paying for it.",
             "Which concession is valuable to the seller but inexpensive for you—and vice versa?",
             [("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:027-negotiating-your-best-deal-part-1-of-2", None, "Negotiating your best deal"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:026-chapter-10show-them-the-money-from-offer-to-purchase-agreement-part-2-of", None, "Negotiating the purchase agreement")]),
            ("04", "Use the option period and inspection well",
             "Buy information quickly, distinguish safety and structural risks from ordinary wear, and resolve defects before the unrestricted exit closes.",
             "Book the inspector immediately. North Texas foundation and drainage concerns can justify a specialist, not just a general inspection.",
             "Which findings require a specialist, a credit, a repair, or a clean exit?",
             [("first-time-home-buyer-2021", "first-time-home-buyer-2021:024-chapter-eleven", "THE HOME INSPECTION", "The home inspection"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:029-chapter-12send-in-the-big-guns-professional-property-inspectors", None, "Professional property inspectors"),
              ("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:029-inspecting-and-protecting-your-home-part-1-of-2", None, "Inspecting and protecting your home")]),
        ],
    },
    {
        "code": "JOURNEY-CONTRACT", "title": "Under contract", "when": "After option through clear-to-close",
        "lessons": [
            ("01", "Keep underwriting and approval alive",
             "Preapproval was only the beginning. Underwriting rechecks income, assets, credit, debts, and the property itself.",
             "Avoid new credit, unexplained transfers, job changes, and missing documents. Use the TREC 40-11 track for the deadline mechanics.",
             "Which household action could change approval between contract and closing?",
             [("first-time-home-buyer-2021", "first-time-home-buyer-2021:025-chapter-twelve", "UNDER CONTRACT", "Under contract"),
              ("fleming-buying-financing-2023", "fleming-buying-financing-2023:p040", "underwriter", "How an underwriter views the file")]),
            ("02", "Understand appraisal and property approval",
             "The lender approves both borrowers and collateral. A low appraisal or property problem can change cash needed and loan eligibility.",
             "Do not confuse preapproval with a promise to finance this house. Track the financing-addendum deadlines separately.",
             "If the appraisal is low, what choices exist—and which depend on a live contract right?",
             [("nolo-essential-guide-2023", "nolo-essential-guide-2023:018-chapter-6bring-home-the-bacon-getting-a-mortgage-part-1-of-2", "appraised value", "Appraisal and the mortgage"),
              ("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:016-mortgage-quandaries-conundrums-and-forms", "appraisal", "Mortgage forms and appraisal questions")]),
            ("03", "Review title, survey, insurance, and warranties",
             "Confirm what you will own, what burdens the property, and what coverage begins when the seller's risk ends.",
             "Read commitments and exceptions, not just summaries. Verify insurability before the contract leaves you without an exit.",
             "Which title exception, survey fact, or insurance limitation would change the decision to buy?",
             [("nolo-essential-guide-2023", "nolo-essential-guide-2023:027-chapter-11toward-the-finish-line-tasks-before-closing-part-1-of-2", "title", "Title, survey, and pre-closing work"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:030-chapter-13whos-got-your-back-homeowners-insurance-and-home-warranties", None, "Homeowners insurance and warranties")]),
            ("04", "Manage the countdown without missing a right",
             "Closing is a chain of documents, approvals, deposits, notices, and dates. One late item can cost leverage or the deal.",
             "Keep one shared timeline for both buyers, lender, agent, title company, inspector, and attorney.",
             "What remains open, who owns it, and what is the last safe date rather than the final possible date?",
             [("first-time-home-buyer-2021", "first-time-home-buyer-2021:025-chapter-twelve", "closing", "The under-contract countdown"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:028-chapter-11toward-the-finish-line-tasks-before-closing-part-2-of-2", None, "Tasks before closing")]),
        ],
    },
    {
        "code": "JOURNEY-CLOSING", "title": "Closing", "when": "Final disclosure through funding",
        "lessons": [
            ("01", "Review final numbers before signing",
             "Compare the Closing Disclosure with the Loan Estimate and contract before urgency makes every discrepancy feel unavoidable.",
             "Question changed lender fees, credits, prepaid items, taxes, insurance, cash-to-close, and wiring instructions before closing day.",
             "Which number changed, why did it change, and who benefits from accepting it?",
             [("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:031-it-aint-over-till-the-escrow-officer-says-so", None, "The closing and escrow process"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:031-chapter-14seal-the-deal-finalizing-your-homebuying-dreams-part-1-of-2", None, "Finalizing the purchase")]),
            ("02", "Final walkthrough, wire, sign, and fund",
             "Confirm the property, repairs, possession, documents, and money are all what the contract requires before ownership transfers.",
             "Verify wire instructions by a known phone number. Signing is not always the same moment as funding or possession.",
             "What must be true before you release funds, and what proof will you keep afterward?",
             [("nolo-essential-guide-2023", "nolo-essential-guide-2023:032-chapter-14seal-the-deal-finalizing-your-homebuying-dreams-part-2-of-2", None, "Walkthrough, signing, and keys"),
              ("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:031-it-aint-over-till-the-escrow-officer-says-so", "walk-through", "Final walkthrough and closing")]),
        ],
    },
    {
        "code": "JOURNEY-MOVE", "title": "Move & settle", "when": "Keys through the first weeks",
        "lessons": [
            ("01", "Move in, secure the property, and preserve the record",
             "Treat the first days as an operational handoff: access, utilities, safety, documents, condition, and the four-dog fence line.",
             "Keep the closing packet, survey, policy, warranties, manuals, inspection, and repair evidence together from day one.",
             "What needs to be secured, transferred, photographed, or filed before ordinary life resumes?",
             [("first-time-home-buyer-2021", "first-time-home-buyer-2021:026-chapter-thirteen", "YOUR FIRST STEPS AS A HOMEOWNER", "Your first steps as a homeowner"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:032-chapter-14seal-the-deal-finalizing-your-homebuying-dreams-part-2-of-2", "keys", "Taking possession and keeping records")]),
            ("02", "Protect cash after closing",
             "The first months bring deposits, tools, repairs, furnishings, and unfamiliar bills. Rebuild reserves before optional improvements.",
             "Separate immediate safety and function from projects that can wait. Monarch remains the money system of record.",
             "Which first-month costs are necessary, and which are excitement wearing a deadline costume?",
             [("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:033-ten-financial-to-dos-after-you-buy", None, "Financial to-dos after you buy"),
              ("first-time-home-buyer-2021", "first-time-home-buyer-2021:026-chapter-thirteen", "AFTER YOU CLOSE", "After you close")]),
        ],
    },
    {
        "code": "JOURNEY-ONGOING", "title": "Ongoing", "when": "The first year and beyond",
        "lessons": [
            ("01", "Start maintenance and records on day one",
             "A home stays understandable when condition, warranties, repairs, contractors, and recurring care are recorded as they happen.",
             "Begin with safety, water, drainage, slab, roof, HVAC, and fence. Use inspection findings as the first maintenance backlog.",
             "What system could fail expensively if nobody records its current condition or next service date?",
             [("first-time-home-buyer-2021", "first-time-home-buyer-2021:026-chapter-thirteen", "maintenance", "Maintenance after closing"),
              ("nolo-essential-guide-2023", "nolo-essential-guide-2023:030-chapter-13whos-got-your-back-homeowners-insurance-and-home-warranties", "warrant", "Insurance, warranties, and future repairs")]),
            ("02", "Plan the first year of ownership",
             "Turn the new property into a stable household: reserve for repairs, review insurance, learn taxes, and pace improvements.",
             "Texas homestead exemption and protest work require current official guidance; the books provide general ownership context only.",
             "What recurring obligation belongs on the calendar, and what improvement can wait until the house has taught you more?",
             [("home-buying-kit-dummies-2025", "home-buying-kit-dummies-2025:033-ten-financial-to-dos-after-you-buy", None, "Financial planning after purchase"),
              ("first-time-home-buyer-2021", "first-time-home-buyer-2021:026-chapter-thirteen", "YOUR FIRST YEAR", "The first year after closing")]),
        ],
    },
]


def focused_excerpt(content: str, phrase: str | None, hint: str | None = None) -> str:
    text = re.sub(r"\r\n?", "\n", content or "").strip()
    if text.startswith("---\n"):
        marker = text.find("\n---", 4)
        if marker >= 0:
            text = text[marker + 4:].lstrip()
    text = re.sub(r"\[Image:[^\]]+\]", "", text)
    text = re.sub(
        r"(?m)^\s*First-Time Home Buyer: The Complete Playbook to Avoiding Rookie Mistakes\s*$",
        "",
        text,
    )
    text = re.sub(r"(?m)^\s*#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*---+\s*$", "", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    deduped = []
    last_nonempty = ""
    for line in text.splitlines():
        normalized = line.strip().casefold()
        if normalized and normalized == last_nonempty:
            continue
        deduped.append(line)
        if normalized:
            last_nonempty = normalized
    text = "\n".join(deduped)
    if not text:
        return ""
    center = 0
    if phrase:
        folded = text.casefold()
        needle = phrase.casefold()
        candidates = []
        offset = 0
        while len(candidates) < 80:
            found = folded.find(needle, offset)
            if found < 0:
                break
            candidates.append(found)
            offset = found + max(1, len(needle))
        if candidates:
            hint_words = set(re.findall(r"[a-z0-9]{4,}", (hint or "").casefold()))
            center = max(candidates, key=lambda found: len(
                hint_words & set(re.findall(r"[a-z0-9]{4,}", folded[max(0, found - 350):found + 350]))
            )) + len(phrase) // 2
    start = max(0, center - MAX_EXCERPT // 3)
    end = min(len(text), start + MAX_EXCERPT)
    start = max(0, end - MAX_EXCERPT)
    if start:
        boundary = max(text.rfind("\n", start, min(end, start + 260)),
                       text.rfind(". ", start, min(end, start + 260)))
        if boundary >= start:
            start = boundary + 1
    if end < len(text):
        boundary = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
        if boundary > start + 700:
            end = boundary + 1
    excerpt = re.sub(r"\n{3,}", "\n\n", text[start:end]).strip()
    return ("…" if start else "") + excerpt + ("…" if end < len(text) else "")


def major_code(code: str) -> str:
    match = re.match(r"^(TREC-(?:20-19|40-11)-P\d{2})", code)
    return match.group(1) if match else code


def locate_section(cx: sqlite3.Connection, citation: dict) -> sqlite3.Row | None:
    return cx.execute(
        """SELECT s.*, b.slug AS book_slug, b.title AS book_title,
                  b.creator, b.text_fidelity
             FROM sections s JOIN books b ON b.id=s.book_id
            WHERE b.slug=? AND s.section_id=? LIMIT 1""",
        (citation.get("book_slug") or citation.get("source_key"), citation.get("section_id")),
    ).fetchone()


def reading_from_section(row: sqlite3.Row, citation: dict, role: str) -> dict:
    return {
        "role": role,
        "book_slug": row["book_slug"],
        "book_title": row["book_title"],
        "creator": row["creator"],
        "section_id": row["section_id"],
        "section_title": row["title"],
        "reading_title": citation.get("label") or row["title"],
        "excerpt": focused_excerpt(row["content"], citation.get("matched_phrase"), citation.get("snippet")),
        "matched_phrase": citation.get("matched_phrase") or "",
        "fidelity": row["fidelity_status"] or row["text_fidelity"],
        "text_fidelity": row["text_fidelity"],
        "source_page": row["source_page"],
        "sha256": row["sha256"],
    }


def build_journey_track(cx: sqlite3.Connection, objectives: dict[str, dict], generated_at: str) -> dict:
    groups = []
    total = 0
    for stage in JOURNEY_CURRICULUM:
        group = {
            "code": stage["code"],
            "title": stage["title"],
            "when": stage["when"],
            "objective_codes": [],
        }
        stage_total = len(stage["lessons"])
        for index, lesson in enumerate(stage["lessons"], start=1):
            suffix, heading, description, guidance, check_prompt, source_specs = lesson
            code = f"{stage['code']}-{suffix}"
            readings = []
            for source_index, (slug, section_id, phrase, label) in enumerate(source_specs):
                citation = {
                    "book_slug": slug,
                    "section_id": section_id,
                    "matched_phrase": phrase,
                    "label": label,
                }
                section = locate_section(cx, citation)
                if not section:
                    raise RuntimeError(f"missing journey source {slug} {section_id}")
                item = reading_from_section(
                    section,
                    citation,
                    "primary_instruction" if source_index == 0 else "supplemental_instruction",
                )
                if not item["excerpt"]:
                    raise RuntimeError(f"empty journey excerpt {code} {section_id}")
                readings.append(item)
            objectives[code] = {
                "code": code,
                "short_code": f"{stage['title']} · {index} of {stage_total}",
                "spine": "journey",
                "heading": heading,
                "description": description,
                "coverage": "curated",
                "guidance": guidance,
                "check_prompt": check_prompt,
                "readings": readings,
            }
            group["objective_codes"].append(code)
            total += 1
        groups.append(group)
    curriculum_hash = hashlib.sha256(
        json.dumps(JOURNEY_CURRICULUM, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return {
        "spine": "journey",
        "name": "Homebuying journey",
        "pack_version": "1.0.0",
        "compiled_at": generated_at,
        "source_set_sha256": curriculum_hash,
        "counts": {
            "total": total,
            "complete": total,
            "thin": 0,
            "partial": 0,
            "gap": 0,
            "ocr_backed": sum(
                1 for code in objectives
                if code.startswith("JOURNEY-") and any(
                    "ocr" in (reading.get("text_fidelity") or "").casefold()
                    for reading in objectives[code]["readings"]
                )
            ),
        },
        "groups": groups,
    }


def export(db_path: Path) -> dict:
    cx = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cx.row_factory = sqlite3.Row
    packs = {}
    for spine in TRACK_NAMES:
        row = cx.execute(
            """SELECT * FROM homestead_packs
                WHERE spine_version=? AND status='ready'
                ORDER BY compiled_at DESC, id DESC LIMIT 1""",
            (spine,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"no ready pack for TREC {spine}")
        packs[spine] = row

    books = [dict(row) for row in cx.execute(
        """SELECT slug,title,creator,section_count,total_words,text_fidelity,
                  corpus_sha256,ingested_at
             FROM books ORDER BY id"""
    )]
    objectives: dict[str, dict] = {}
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    tracks = [build_journey_track(cx, objectives, generated_at)]
    for spine, track_name in TRACK_NAMES.items():
        pack = packs[spine]
        rows = cx.execute(
            """SELECT o.code,o.description,d.heading,d.coverage_status,d.dossier_json
                 FROM objective_dossiers d
                 JOIN objectives o ON o.id=d.objective_id
                WHERE d.pack_id=? ORDER BY o.code""",
            (pack["id"],),
        ).fetchall()
        groups: dict[str, dict] = {}
        for row in rows:
            dossier = json.loads(row["dossier_json"])
            code = row["code"]
            group_code = major_code(code)
            group = groups.setdefault(group_code, {
                "code": group_code,
                "title": row["heading"].split(" - ", 1)[0],
                "objective_codes": [],
            })
            group["objective_codes"].append(code)

            readings = []
            seen_books = set()
            primary = dossier.get("primary_citations") or []
            supplemental = dossier.get("supplemental_citations") or []
            citations = [*primary]
            if row["coverage_status"] != "complete" or not primary:
                citations.extend(supplemental)
            citations.sort(key=lambda item: (
                item.get("use_role") != "primary_instruction",
                "table of contents" in (item.get("section_title") or "").casefold(),
            ))
            for citation in citations:
                slug = citation.get("book_slug") or citation.get("source_key")
                if not slug or slug in seen_books or len(seen_books) >= MAX_BOOK_READINGS:
                    continue
                section = locate_section(cx, citation)
                if not section:
                    continue
                role = citation.get("use_role") or "supplemental_instruction"
                item = reading_from_section(section, citation, role)
                if item["excerpt"]:
                    readings.append(item)
                    seen_books.add(slug)

            for remediation in (dossier.get("remediated_by") or [])[:1]:
                citation = {
                    "book_slug": remediation.get("source_key"),
                    "source_key": remediation.get("source_key"),
                    "section_id": remediation.get("section_id"),
                    "matched_phrase": None,
                }
                section = locate_section(cx, citation)
                if section:
                    item = reading_from_section(section, citation, "derived")
                    item["depth"] = remediation.get("depth")
                    readings.append(item)

            objectives[code] = {
                "code": code,
                "short_code": code.replace("TREC-", "").replace("-P", " ¶"),
                "spine": spine,
                "heading": row["heading"],
                "description": row["description"],
                "coverage": row["coverage_status"],
                "guidance": dossier.get("guidance") or "",
                "readings": readings,
            }

        tracks.append({
            "spine": spine,
            "name": track_name,
            "pack_version": pack["pack_version"],
            "compiled_at": pack["compiled_at"],
            "source_set_sha256": pack["source_set_sha256"],
            "counts": {
                "total": pack["objective_count"],
                "complete": pack["complete_count"],
                "thin": pack["thin_count"],
                "partial": pack["partial_count"],
                "gap": pack["coverage_gap_count"],
                "ocr_backed": pack["ocr_backed_objective_count"],
            },
            "groups": list(groups.values()),
        })

    payload = {
        "schema_version": 1,
        "generated_at": generated_at,
        "metadata": {
            "objective_count": len(objectives),
            "journey_lesson_count": tracks[0]["counts"]["total"],
            "contract_objective_count": sum(t["counts"]["total"] for t in tracks if t["spine"] != "journey"),
            "book_count": sum(1 for b in books if not b["slug"].startswith("homestead-")),
            "source_word_count": sum(b["total_words"] for b in books if not b["slug"].startswith("homestead-")),
        },
        "books": books,
        "tracks": tracks,
        "objectives": objectives,
    }
    if len(objectives) != sum(t["counts"]["total"] for t in tracks):
        raise RuntimeError("objective count mismatch")
    if any(len(r["excerpt"]) > MAX_EXCERPT + 2 for o in objectives.values() for r in o["readings"]):
        raise RuntimeError("excerpt bound exceeded")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = export(args.database)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "bytes": args.output.stat().st_size,
        "objectives": payload["metadata"]["objective_count"],
        "books": payload["metadata"]["book_count"],
    }))


if __name__ == "__main__":
    main()
