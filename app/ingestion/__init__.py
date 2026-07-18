from typing import Any, Callable

from app.schema.canonical import LeadSource

from .facebook import parse_facebook_input
from .google_form import parse_google_form_csv
from .instagram import parse_instagram_csv
from .landing_page import parse_landing_page_input

# Facebook and landing-page loaders accept a parsed dict/list (calling
# in-process) or raw text that's either a single JSON document or JSONL
# (one lead per line) -- auto-detected, see parse_facebook_input /
# parse_landing_page_input. Instagram/Google Form are always CSV text.
SOURCE_LOADERS: dict[LeadSource, Callable[[Any], list[dict[str, Any]]]] = {
    LeadSource.FACEBOOK: parse_facebook_input,
    LeadSource.INSTAGRAM: parse_instagram_csv,
    LeadSource.GOOGLE_FORM: parse_google_form_csv,
    LeadSource.LANDING_PAGE: parse_landing_page_input,
}


def ingest(source: LeadSource, raw_data: Any) -> list[dict[str, Any]]:
    """Dispatch raw input to the loader for its source and tag each
    resulting record with where it came from, before any field mapping
    or cleaning has happened."""
    loader = SOURCE_LOADERS[source]
    records = loader(raw_data)
    for record in records:
        record.setdefault("_source", source.value)
    return records
