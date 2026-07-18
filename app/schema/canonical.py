"""Canonical lead schema. Every source format gets mapped into this shape
before cleaning, validation, dedup, and scoring operate on it."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


def _is_mostly_letters(value: str) -> bool:
    """True if at least half the non-space characters are Unicode letters
    (any script -- Latin, Han, Arabic, Cyrillic, ...). Rejects
    emoji/symbol junk, including one real letter padded with emoji to
    dodge a simpler "contains at least one letter" check (e.g. "\U0001F602A"),
    while still accepting legitimate names with apostrophes/hyphens
    ("O'Brien", "Anne-Marie") and non-English scripts."""
    chars = [ch for ch in value if not ch.isspace()]
    if not chars:
        return False
    letters = sum(1 for ch in chars if unicodedata.category(ch).startswith("L"))
    return letters / len(chars) > 0.5


class LeadSource(str, Enum):
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    GOOGLE_FORM = "google_form"
    LANDING_PAGE = "landing_page"


class LeadStatus(str, Enum):
    # A Lead object only ever exists once it's passed Pydantic validation
    # (a row that fails validation never becomes a Lead -- it's stored as
    # a raw dict in invalid_leads instead, see app/validation/validator.py),
    # so status only ever needs to distinguish three outcomes from there:
    CLEAN = "clean"  # passed validation, no quality concerns
    FLAGGED = "flagged"  # passed validation, but scoring found a quality concern
    # (disposable email domain, placeholder/keyboard-mash name, etc. --
    # see app/agent/pipeline.py) worth a human's attention before treating
    # it like a normal lead
    DUPLICATE = "duplicate"  # merged into another kept lead, see app/deduplication


class Lead(BaseModel):
    lead_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone_e164: str = Field(pattern=r"^\+[1-9]\d{6,14}$")
    source: LeadSource
    campaign_id: Optional[str] = None
    consent: bool
    created_at: datetime
    quality_score: Optional[float] = Field(default=None, ge=0, le=100)
    status: LeadStatus = LeadStatus.CLEAN
    # Populated when status == "duplicate": which kept lead this one was
    # merged into, so a merge can be traced/audited later instead of the
    # discarded record just vanishing into an anonymous pile.
    duplicate_of_lead_id: Optional[str] = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("first_name", "last_name")
    @classmethod
    def reject_non_alphabetic_junk(cls, v: str) -> str:
        if not _is_mostly_letters(v):
            raise ValueError("name must be mostly letters -- got mostly non-alphabetic characters (e.g. emoji/symbols)")
        return v

    class Config:
        use_enum_values = True


# Field descriptions used both as documentation and as the RAG corpus the
# mapping module embeds into ChromaDB so the LLM can ground its field
# mapping guesses in what each canonical field actually means.
CANONICAL_FIELD_DESCRIPTIONS: dict[str, str] = {
    "first_name": "The lead's given/first name. Source fields like 'fname', 'First Name', or the first token of a combined 'Full Name' map here.",
    "last_name": "The lead's family/last name. Source fields like 'lname', 'Last Name', or remaining tokens of a combined 'Full Name' map here.",
    "email": "The lead's email address. Source fields like 'email', 'Email Address', 'contact_email' map here.",
    "phone_e164": "The lead's phone number, to be normalized to E.164 format. Source fields like 'phone', 'Phone Number', 'mobile', 'whatsapp' map here.",
    "source": "Which channel the lead came from: facebook, instagram, google_form, or landing_page. Usually known from the ingestion context, not a source field.",
    "campaign_id": "An ad or form campaign identifier. Source fields like 'campaign_id', 'ad_id', 'utm_campaign', 'form_id' map here.",
    "consent": "Whether the lead consented to marketing contact. Source fields like 'consent', 'opt_in', 'marketing_consent', 'gdpr_consent' map here.",
    "created_at": "Timestamp the lead was captured. Source fields like 'created_time', 'timestamp', 'Submitted At', 'date' map here.",
}

CANONICAL_FIELDS = list(CANONICAL_FIELD_DESCRIPTIONS.keys())
