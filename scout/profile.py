"""Owner-supplied buying criteria and the deterministic assessment built from them.

Two rules govern this module.

**Nothing is fabricated.** Every weight here comes from a criterion the buyers
actually supplied. The `$425,000` ceiling and the Richardson/Garland city list were given
explicitly on 2026-08-09. Everything else -- bedrooms, bathrooms, property type, acreage,
lot size, HOA tolerance, year built, school ratings -- is deliberately unset, is reported
as unset in every assessment, and contributes nothing to the score.

**No profile means no score.** With no owner-approved profile, leads are ingested and
listed `unranked`, and the UI says why. A guessed score is worse than a blank one: it
reads as an opinion the household never expressed.
"""
import hashlib
import json

# Criteria the household has not supplied. Listed explicitly so an assessment can state
# what it did NOT consider, rather than implying a whole-property judgement.
UNSET_CRITERIA = (
    "bedrooms",
    "bathrooms",
    "property type",
    "lot size / acreage",
    "HOA tolerance",
    "year built",
    "schools",
    "fenced yard for four dogs",
)

_BASE_SCORE = 50
_MATCH_BONUS = 25
_MISS_PENALTY = 40


def _clean_cities(value):
    if not isinstance(value, list):
        return []
    seen = []
    for item in value:
        city = " ".join(str(item or "").split()).title()
        if city and city not in seen:
            seen.append(city)
    return seen


def validate_profile(payload):
    """Normalize an owner-supplied profile, or explain why it is not usable."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "profile must be a JSON object"}

    profile = {}

    raw_price = payload.get("max_price")
    if raw_price is not None:
        try:
            max_price = int(raw_price)
        except (TypeError, ValueError):
            return {"ok": False, "error": "max_price must be a whole number of dollars"}
        if max_price <= 0:
            return {"ok": False, "error": "max_price must be greater than zero"}
        profile["max_price"] = max_price

    cities = _clean_cities(payload.get("cities"))
    if cities:
        profile["cities"] = cities

    if not profile:
        return {"ok": False, "error": "supply at least one criterion (max_price or cities)"}
    return {"ok": True, "profile": profile}


def profile_hash(profile):
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assess(fields, profile):
    """Deterministic, explainable assessment of one lead against the owner profile.

    Returns None when there is no profile: the caller stores NULL score/label and the UI
    shows the lead as unranked. There is no fallback heuristic on purpose.
    """
    if not profile:
        return None

    score = _BASE_SCORE
    reasons = []
    cautions = []
    considered = []

    max_price = profile.get("max_price")
    if max_price:
        considered.append("asking price")
        price = fields.get("price")
        if isinstance(price, (int, float)) and price > 0:
            if price <= max_price:
                score += _MATCH_BONUS
                reasons.append(f"Asking ${int(price):,} is within the ${max_price:,} ceiling")
            else:
                score -= _MISS_PENALTY
                over = int(price) - max_price
                cautions.append(
                    f"Asking ${int(price):,} is ${over:,} over the ${max_price:,} ceiling"
                )
        else:
            cautions.append("The alert did not state an asking price")

    cities = profile.get("cities")
    if cities:
        considered.append("city")
        city = " ".join(str(fields.get("city") or "").split()).title()
        if city:
            if city in cities:
                score += _MATCH_BONUS
                reasons.append(f"{city} is one of the approved cities")
            else:
                score -= _MISS_PENALTY
                cautions.append(f"{city} is outside {' and '.join(cities)}")
        else:
            cautions.append("The alert did not state a city")

    score = max(0, min(100, score))
    if score >= 75:
        label = "matches your criteria"
    elif score >= 50:
        label = "partial match"
    else:
        label = "outside your criteria"

    return {
        "score": score,
        "label": label,
        "reasons": reasons,
        "cautions": cautions,
        "criteria_considered": considered,
        "criteria_not_set": list(UNSET_CRITERIA),
        "note": (
            "Scored only on the criteria the buyers supplied. Everything listed in "
            "criteria_not_set was not considered. Verify the live listing with Homestead "
            "Capture before filing it in Properties."
        ),
    }
