"""Canonical lead schema. Every source format gets mapped into this shape
before cleaning, validation, dedup, and scoring operate on it."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, Field, field_validator


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
    # The brief is explicit that a lead a business paid for is never
    # deleted for having dirty data -- every row that makes it through
    # ingestion becomes a Lead, no matter how incomplete. status is what
    # distinguishes a usable record from one worth a human's attention:
    CLEAN = "clean"  # passed validation, no quality concerns
    FLAGGED = "flagged"  # missing/malformed required-ish data (name, email,
    # phone), or a quality concern found by scoring (disposable email
    # domain, placeholder/keyboard-mash name, placeholder phone, no
    # contactable identifier at all) -- see app/agent/pipeline.py
    DUPLICATE = "duplicate"  # merged into another kept lead, see app/deduplication
    # A row that's structurally unusable (see app/validation/validator.py
    # for the now very narrow set of things that still qualify) never
    # becomes a Lead at all -- it's stored as a raw dict in invalid_leads
    # instead, so there's no LeadStatus for that outcome.


class Lead(BaseModel):
    lead_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # first_name/last_name/email/phone_e164/consent are all nullable per
    # the brief's own schema -- a lead with a junk phone number, a
    # malformed email, or a missing name is still a lead a business paid
    # for. It gets flagged (see _flag_quality_concerns in
    # app/agent/pipeline.py) and scored low (has_first_name/has_email/etc
    # in app/scoring/features.py already treat a missing field as a
    # quality signal, not a rejection reason) -- never dropped.
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = None
    phone_e164: Optional[str] = Field(default=None, pattern=r"^\+[1-9]\d{6,14}$")
    source: LeadSource
    campaign_id: Optional[str] = None
    # Missing/unparseable consent defaults to False (TCPA-safe: silence is
    # never treated as opt-in) rather than being required -- see
    # app/cleaning/transforms.py:normalize_consent, which now always
    # returns a bool.
    consent: bool = False
    created_at: datetime
    quality_score: Optional[float] = Field(default=None, ge=0, le=100)
    status: LeadStatus = LeadStatus.CLEAN
    # Populated when status == "duplicate": which kept lead this one was
    # merged into, so a merge can be traced/audited later instead of the
    # discarded record just vanishing into an anonymous pile.
    duplicate_of_lead_id: Optional[str] = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("consent", mode="before")
    @classmethod
    def default_missing_consent(cls, v: Any) -> Any:
        # app/cleaning/transforms.py:normalize_consent already does this
        # in the real pipeline (and handles the phrase-parsing) -- this
        # is the same defense-in-depth backstop as the email/name
        # validators above, for any caller that constructs a Lead
        # directly without going through cleaning first.
        return False if v is None else v

    @field_validator("created_at", mode="before")
    @classmethod
    def default_missing_timestamp(cls, v: Any) -> Any:
        # parse_datetime_utc returns None for an unparseable/missing
        # source timestamp -- same "never drop for dirty data" policy as
        # every other field, just with "now" as the sane default instead
        # of None, since sorting/tiebreaking (app/deduplication/dedup.py)
        # needs a real, comparable datetime.
        return v if v is not None else datetime.now(timezone.utc)

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def null_out_non_alphabetic_junk(cls, v: Any) -> Any:
        # A keyboard-mash/emoji-only "name" isn't usable data, but it's
        # not a reason to drop the whole lead either -- treat it the same
        # as a genuinely missing name (None), which the scoring layer
        # already penalizes via has_first_name/has_last_name and
        # name_is_placeholder_like, and _flag_quality_concerns marks
        # FLAGGED rather than silently keeping it as a fake-looking clean
        # lead.
        if v is None or not isinstance(v, str):
            return v
        return v if _is_mostly_letters(v) else None

    @field_validator("email", mode="before")
    @classmethod
    def normalize_or_null_email(cls, v: Any) -> Any:
        # app/cleaning/transforms.py:normalize_email already normalizes
        # (or nulls out) email before it reaches here in the real
        # pipeline -- this is a defense-in-depth backstop for any other
        # caller that constructs a Lead directly (tests, scripts), so an
        # unparseable email degrades to "no email on file" instead of
        # rejecting the entire lead.
        if v is None:
            return None
        try:
            return validate_email(str(v), check_deliverability=False).normalized.lower()
        except EmailNotValidError:
            return None

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
