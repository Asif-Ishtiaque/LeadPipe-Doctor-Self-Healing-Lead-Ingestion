"""Generates synthetic messy lead data across all 4 supported sources,
matching the team's official sample-data spec (file names, formats, and
intentional mess described in data/sample_pack/README.md).

Produces:
  data/raw/facebook_leads.jsonl   -- Facebook Lead Ads webhook payloads,
                                     one complete delivery per line
  data/raw/instagram_export.csv   -- Ads Manager-style CSV export
  data/raw/google_form.csv        -- Google Forms response export,
                                     question-style headers
  data/raw/landing_page.jsonl     -- flat landing-page JSON, one lead
                                     per line

Deliberately messy: 7+ phone formats (including pure junk), typo/junk
emails, ~25% cross-source duplicate people, missing fields, mixed date
formats (epoch/ISO/US/DD-Mon-YYYY), every common consent encoding,
ALL-CAPS and emoji names, and empty rows.

Run with: python -m scripts.generate_data --total 100000
"""

from __future__ import annotations

import argparse
import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from faker import Faker

fake = Faker()

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

# Weighted so most phones stay parseable-but-differently-formatted (the
# cleaning engine's job) and a minority are genuinely broken (the
# validation layer's job to reject) -- includes the spec's named formats:
# "+1 (555) 123-4567", "555-123-4567", "5551234567", "1-555-...", and pure
# junk ("12345", "N/A", "000-000-0000").
PHONE_FORMATS = [
    (lambda n: f"+1 ({n[:3]}) {n[3:6]}-{n[6:]}", 3),
    (lambda n: f"{n[:3]}-{n[3:6]}-{n[6:]}", 3),
    (lambda n: n, 3),  # bare digits, no formatting -- still parseable
    (lambda n: f"1-{n[:3]}-{n[3:6]}-{n[6:]}", 2),
    (lambda n: f"({n[:3]}) {n[3:6]}-{n[6:]}", 2),
    (lambda n: f"{n[3:6]}.{n[6:]}", 1),  # missing area code -- ambiguous/messy on purpose
    (lambda n: "12345", 1),  # pure junk
    (lambda n: "N/A", 1),  # pure junk
    (lambda n: "000-000-0000", 1),  # pure junk
]

def _fake_test_email(e: str) -> str:
    """Obviously fake, but still per-person unique with a digits-only
    suffix ("test1182@test.com", not "test.johndoe@test.com") -- a bare
    "test@test.com" for every occurrence would make every one of these
    records exact-email-match each other and collapse into a single
    duplicate cluster instead of each being individually caught; a
    non-digit suffix like ".johndoe" wouldn't trip the placeholder-email
    scoring signal at all, which only matches token+digits, not
    token+anything, to avoid flagging real words/names like
    "testimonials"."""
    match = re.search(r"(\d+)@", e)
    suffix = match.group(1) if match else "0"
    return f"test{suffix}@test.com"


# Weighted so most emails stay valid (possibly just re-cased) and a
# minority are genuinely malformed, typo'd, or obviously fake -- includes
# the spec's named junk: "test@test.com", "asdf@asdf", "@gmial.com" typo.
EMAIL_MANGLERS = [
    (lambda e: e, 5),
    (lambda e: e.upper(), 2),
    (lambda e: e.replace("@gmail.com", "@gmial.com").replace("@yahoo.com", "@yahooo.com"), 1),  # typo domain
    (lambda e: e.replace("@", " at "), 1),  # malformed
    (lambda e: e.split("@")[0], 1),  # missing domain
    (_fake_test_email, 1),
    (lambda e: "asdf@asdf", 1),  # invalid, missing TLD
    (lambda e: "", 1),
]

# The spec's exact consent encodings: "Yes/yes/Y/TRUE/I agree/empty/boolean".
CONSENT_TRUE_VALUES = ["Yes", "yes", "Y", "TRUE", "I agree", True]
CONSENT_FALSE_VALUES = ["No", "no", "N", "FALSE", "I do not agree", False]


def messy_phone(digits: str) -> str | None:
    if random.random() < 0.03:
        return None
    funcs, weights = zip(*PHONE_FORMATS)
    return random.choices(funcs, weights=weights, k=1)[0](digits)


def messy_email(email: str) -> str | None:
    if random.random() < 0.03:
        return None
    funcs, weights = zip(*EMAIL_MANGLERS)
    return random.choices(funcs, weights=weights, k=1)[0](email)


def messy_created_at(dt: datetime) -> str | int:
    fmt = random.choice([
        "epoch",
        "%Y-%m-%dT%H:%M:%SZ",  # ISO 8601
        "%m/%d/%Y %I:%M %p",  # MM/DD/YYYY hh:mm AM
        "%d-%b-%Y",  # DD-Mon-YYYY
    ])
    if fmt == "epoch":
        return int(dt.timestamp())
    return dt.strftime(fmt)


def messy_consent(consent: bool) -> str | bool:
    if random.random() < 0.05:
        return ""  # empty/unanswered
    return random.choice(CONSENT_TRUE_VALUES if consent else CONSENT_FALSE_VALUES)


def messy_name(name: str) -> str:
    roll = random.random()
    if roll < 0.05:
        return name.upper()  # ALL-CAPS
    if roll < 0.08:
        return f"{name} {random.choice(['😀', '🔥', '✨', '💯'])}"  # emoji in name
    return name


# Real, currently-assigned US area codes. `phonenumbers.is_valid_number`
# checks against actual NANP assignment data, not just the area-code/exchange
# digit-pattern rules -- fake.msisdn() and hand-rolled digits both produced
# mostly "invalid" numbers because the area codes weren't real, so sample
# from a real list instead.
REAL_US_AREA_CODES = [
    "201", "202", "203", "205", "206", "212", "213", "214", "215", "216",
    "217", "218", "224", "281", "301", "302", "303", "304", "305", "312",
    "313", "314", "315", "316", "317", "319", "404", "405", "406", "407",
    "408", "409", "410", "412", "413", "414", "415", "416", "501", "502",
    "503", "504", "505", "512", "513", "515", "516", "517", "518", "601",
    "602", "603", "605", "606", "607", "608", "609", "610", "612", "614",
    "615", "616", "617", "618", "619", "702", "703", "704", "706", "707",
    "708", "713", "714", "715", "716", "717", "718", "719", "801", "802",
    "803", "804", "805", "806", "808", "810", "812", "813", "814", "815",
    "816", "901", "903", "904", "906", "907", "908", "909", "910", "912",
]


def _valid_nanp_digits() -> str:
    """A phonenumbers-valid North American 10-digit number: real area code,
    exchange not starting with 0/1 (per NANP rules)."""
    area = random.choice(REAL_US_AREA_CODES)
    exchange = f"{random.randint(2, 9)}{random.randint(0, 9)}{random.randint(0, 9)}"
    line = f"{random.randint(0, 9999):04d}"
    return area + exchange + line


def make_person(i: int) -> dict:
    first = fake.first_name()
    last = fake.last_name()
    digits = _valid_nanp_digits()
    return {
        "person_id": i,
        "first_name": first,
        "last_name": last,
        "email": f"{first.lower()}.{last.lower()}{i}@{fake.free_email_domain()}",
        "phone_digits": digits,
        "consent": random.random() > 0.25,
        "campaign_id": f"camp_{random.randint(1, 40)}",
        "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(0, 90), hours=random.randint(0, 23)),
    }


def to_facebook_entry(person: dict) -> dict:
    """One line of facebook_leads.jsonl -- one complete webhook delivery."""
    if random.random() < 0.02:  # empty/junk row
        return {"entry": [{"id": "1000000000", "time": 0, "changes": []}]}

    field_data = [
        {"name": "full_name", "values": [messy_name(f"{person['first_name']} {person['last_name']}")]},
        {"name": "email", "values": [messy_email(person["email"]) or ""]},
        {"name": "phone_number", "values": [messy_phone(person["phone_digits"]) or ""]},
        {"name": "consent", "values": [str(messy_consent(person["consent"]))]},
    ]
    if random.random() < 0.1:  # missing fields, dropped randomly (per spec)
        field_data = [f for f in field_data if f["name"] != "full_name"]

    created_at = messy_created_at(person["created_at"])
    created_time = created_at if isinstance(created_at, int) else int(person["created_at"].timestamp())

    return {
        "entry": [
            {
                "id": "1000000000",
                "time": created_time,
                "changes": [
                    {
                        "field": "leadgen",
                        "value": {
                            "leadgen_id": f"fb_{person['person_id']}",
                            "page_id": "1000000000",
                            "form_id": person["campaign_id"],
                            "created_time": created_time,
                            "field_data": field_data,
                        },
                    }
                ],
            }
        ]
    }


def to_instagram_row(person: dict) -> dict:
    if random.random() < 0.02:  # empty/junk row
        return {}
    return {
        "Full Name": messy_name(f"{person['first_name']} {person['last_name']}") if random.random() > 0.05 else None,
        "E-mail": messy_email(person["email"]),
        "Phone #": messy_phone(person["phone_digits"]),
        "Date": messy_created_at(person["created_at"]),
        "Ad ID": person["campaign_id"],
        "Opted In": messy_consent(person["consent"]),
    }


def to_google_form_row(person: dict) -> dict:
    """Question-style headers, the way a real Google Form export names
    columns after whatever the form author actually typed."""
    if random.random() < 0.02:  # empty/junk row
        return {}
    return {
        "Timestamp": messy_created_at(person["created_at"]),
        "What's your name?": messy_name(f"{person['first_name']} {person['last_name']}") if random.random() > 0.05 else None,
        "Your email address": messy_email(person["email"]),
        "Best number to reach you": messy_phone(person["phone_digits"]),
        "Do you agree to be contacted?": messy_consent(person["consent"]),
        "How did you hear about us?": person["campaign_id"],
    }


def to_landing_page_record(person: dict) -> dict:
    """One line of landing_page.jsonl."""
    if random.random() < 0.02:  # empty/junk row
        return {}
    return {
        "fname": messy_name(person["first_name"]) if random.random() > 0.05 else None,
        "lname": person["last_name"] if random.random() > 0.05 else None,
        "email_addr": messy_email(person["email"]),
        "mobile": messy_phone(person["phone_digits"]),
        "opt_in": messy_consent(person["consent"]),
        "utm_campaign": person["campaign_id"],
        "utm_source": "landing_page",
        "ts": messy_created_at(person["created_at"]),
    }


def duplicate_with_drift(person: dict) -> dict:
    """Same person submitting again -- formatting drifts slightly but it's
    still recognizably them, for the dedup engine to catch."""
    drifted = dict(person)
    if random.random() > 0.5:
        drifted["email"] = person["email"].upper()
    return drifted


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=100_000, help="approx total raw submissions across all sources")
    parser.add_argument("--duplicate-rate", type=float, default=0.25, help="~fraction of unique people who also appear in another source")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=str, default=None, help="defaults to data/raw")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR

    random.seed(args.seed)
    Faker.seed(args.seed)

    n_unique = int(args.total / (1 + args.duplicate_rate))
    people = [make_person(i) for i in range(n_unique)]

    submissions = list(people)
    n_duplicates = int(n_unique * args.duplicate_rate)
    submissions += [duplicate_with_drift(random.choice(people)) for _ in range(n_duplicates)]
    random.shuffle(submissions)

    buckets = {"facebook": [], "instagram": [], "google_form": [], "landing_page": []}
    for person in submissions:
        buckets[random.choice(list(buckets.keys()))].append(person)

    out_dir.mkdir(parents=True, exist_ok=True)

    _write_jsonl(out_dir / "facebook_leads.jsonl", [to_facebook_entry(p) for p in buckets["facebook"]])

    pd.DataFrame([to_instagram_row(p) for p in buckets["instagram"]]).to_csv(
        out_dir / "instagram_export.csv", index=False
    )
    pd.DataFrame([to_google_form_row(p) for p in buckets["google_form"]]).to_csv(
        out_dir / "google_form.csv", index=False
    )
    _write_jsonl(out_dir / "landing_page.jsonl", [to_landing_page_record(p) for p in buckets["landing_page"]])

    print(f"Generated {len(submissions)} raw submissions from {n_unique} unique people:")
    for source, records in buckets.items():
        print(f"  {source}: {len(records)} records -> {out_dir}/")


if __name__ == "__main__":
    main()
