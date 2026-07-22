"""Human-readable lead diagnosis and a suggested next action.

Both are derived deterministically from the same feature vector the scorer
already computes (app/scoring/features.py) plus the lead's status and
quality_score -- no separate LLM call. That's deliberate: a sales manager
needs the "why" behind a score to be specific, consistent run-to-run, and
instant, none of which a generative model guarantees. Every phrase below
maps to a concrete, inspectable signal, so the explanation can never drift
from the number it's explaining.

diagnose(lead) -> "why this score", e.g.
  "Medium-quality lead (score 55). Strengths: non-personal email domain,
   both email and phone captured. Concerns: no marketing consent
   captured."

suggest_action(lead) -> what a rep should do next, e.g.
  "Add to an email nurture sequence; escalate to a rep if they engage.
   No consent on file: do not cold-call (TCPA), email only with a lawful
   basis."
"""

from __future__ import annotations

from app.schema.canonical import Lead
from app.scoring.features import build_features


def _positive_signals(lead: Lead, f: dict[str, float]) -> list[str]:
    signals: list[str] = []
    if f["consent"]:
        signals.append("opted in to contact")
    if (
        f["has_email"]
        and not f["email_is_free_provider"]
        and not f["email_is_disposable"]
        and not f["email_is_placeholder_like"]
    ):
        # We only check the domain isn't a known free/disposable/placeholder
        # provider -- we don't verify a real company, so claim exactly that.
        signals.append("non-personal email domain")
    if f["has_email"] and f["has_phone"]:
        # Both fields are present; we haven't pinged the inbox or dialled the
        # number, so "captured" is the honest word, not "reachable".
        signals.append("both email and phone captured")
    if f["has_campaign_id"] and lead.campaign_id:
        signals.append(f"attributed to campaign '{lead.campaign_id}'")
    return signals


def _negative_signals(lead: Lead, f: dict[str, float]) -> list[str]:
    neg: list[str] = []
    if not f["has_email"] and not f["has_phone"]:
        neg.append("no email or phone on file")
    if not f["consent"]:
        neg.append("no marketing consent captured")
    if f["email_is_disposable"]:
        neg.append("disposable/throwaway email domain")
    if f["email_is_placeholder_like"]:
        neg.append("placeholder-looking email (e.g. test@)")
    if f["name_is_placeholder_like"]:
        neg.append("placeholder or keyboard-mash name")
    if f["phone_is_placeholder"]:
        neg.append("unverifiable 555 phone number")
    if f["email_is_free_provider"]:
        neg.append("personal (free) email, not a company domain")
    if not f["has_first_name"] and not f["has_last_name"]:
        neg.append("no name captured")
    return neg


def band(score: float) -> str:
    # Band on the integer the user actually sees, not the raw float --
    # otherwise a 69.88 displays as "score 70" but bands as Medium
    # (>=70 is High), which reads as a contradiction. Round once, use it
    # for both the label and the number.
    shown = round(score)
    if shown >= 70:
        return "High"
    if shown >= 40:
        return "Medium"
    return "Low"


def diagnose(lead: Lead) -> str:
    f = build_features(lead)
    pos = _positive_signals(lead, f)
    neg = _negative_signals(lead, f)

    if lead.quality_score is None:
        parts = ["Not yet scored."]
    else:
        parts = [f"{band(lead.quality_score)}-quality lead (score {lead.quality_score:.0f})."]
    if pos:
        parts.append("Strengths: " + ", ".join(pos) + ".")
    if neg:
        parts.append("Concerns: " + ", ".join(neg) + ".")
    if not pos and not neg:
        parts.append("No standout signals either way -- an ordinary, complete lead.")
    return " ".join(parts)


def suggest_action(lead: Lead) -> str:
    f = build_features(lead)
    score = lead.quality_score if lead.quality_score is not None else 0.0

    # Hard blockers first -- these override the score band entirely, because
    # spending rep time on an uncontactable or obviously-fake lead is waste
    # no matter what the model scored it.
    if not f["has_email"] and not f["has_phone"]:
        return (
            "Do not action yet -- no email or phone captured. "
            "Check the source form for a broken or unmapped contact field."
        )
    if f["email_is_disposable"] or f["email_is_placeholder_like"] or f["name_is_placeholder_like"]:
        return (
            "Verify before any outreach -- the email or name looks fake or test-generated. "
            "Confirm this is a real person before a rep spends time on it."
        )

    # Same band() the diagnosis uses, so "High-quality (score 70)" and the
    # action can never disagree about which tier the lead is in.
    tier = band(score)
    if tier == "High":
        base = "Contact within 24 hours -- high-quality, prioritize for a rep."
    elif tier == "Medium":
        base = "Add to an email nurture sequence; escalate to a rep if they engage."
    else:
        base = "Deprioritize -- low quality, not worth rep time right now."

    if not f["consent"]:
        base += " No consent on file: do not cold-call (TCPA), email only with a lawful basis."
    return base
