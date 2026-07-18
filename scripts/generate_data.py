"""Generates synthetic messy lead data across all 4 supported sources.

Produces:
  data/raw/facebook_leads.json    -- nested Facebook Lead Ads webhook JSON
  data/raw/instagram_leads.csv    -- flat Instagram CSV export
  data/raw/google_form_leads.csv  -- flat Google Form CSV export
  data/raw/landing_page_leads.json -- flat landing-page JSON array

Deliberately messy: inconsistent phone formats, malformed/missing emails,
missing fields, and cross-source duplicate submissions of the same person
(with slightly different formatting each time) so the cleaning,
validation, and deduplication stages all have real work to do.

Run with: python -m scripts.generate_data --total 100000
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from faker import Faker

fake = Faker()

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

# Weighted so most phones stay parseable-but-differently-formatted (the
# cleaning engine's job) and a minority are genuinely broken (the
# validation layer's job to reject).
PHONE_FORMATS = [
    (lambda n: f"+1{n}", 3),
    (lambda n: f"({n[:3]}) {n[3:6]}-{n[6:]}", 3),
    (lambda n: f"{n[:3]}-{n[3:6]}-{n[6:]}", 3),
    (lambda n: f"1-{n[:3]}-{n[3:6]}-{n[6:]}", 2),
    (lambda n: n, 2),  # bare digits, no formatting -- still parseable
    (lambda n: f"{n[3:6]}.{n[6:]}", 1),  # missing area code -- ambiguous/messy on purpose
    (lambda n: "call me maybe", 1),  # garbage, unrecoverable
]

# Weighted so most emails stay valid (possibly just re-cased) and a
# minority are genuinely malformed or missing.
EMAIL_MANGLERS = [
    (lambda e: e, 5),
    (lambda e: e.upper(), 2),
    (lambda e: e.replace("@", " at "), 1),  # malformed
    (lambda e: e.split("@")[0], 1),  # missing domain
    (lambda e: "", 1),
]


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


def messy_created_at(dt: datetime) -> str:
    fmt = random.choice([
        "%Y-%m-%dT%H:%M:%SZ",
        "%m/%d/%Y %H:%M",
        "%d-%m-%Y",
        "%B %d, %Y %I:%M %p",
    ])
    return dt.strftime(fmt)


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
    field_data = [
        {"name": "full_name", "values": [f"{person['first_name']} {person['last_name']}"]},
        {"name": "email", "values": [messy_email(person["email"]) or ""]},
        {"name": "phone_number", "values": [messy_phone(person["phone_digits"]) or ""]},
        {"name": "consent", "values": ["yes" if person["consent"] else "no"]},
    ]
    if random.random() > 0.1:  # occasionally missing name entirely
        pass
    else:
        field_data = [f for f in field_data if f["name"] != "full_name"]

    return {
        "id": "1000000000",
        "time": int(person["created_at"].timestamp()),
        "changes": [
            {
                "field": "leadgen",
                "value": {
                    "leadgen_id": f"fb_{person['person_id']}",
                    "page_id": "1000000000",
                    "form_id": person["campaign_id"],
                    "created_time": int(person["created_at"].timestamp()),
                    "field_data": field_data,
                },
            }
        ],
    }


def to_instagram_row(person: dict) -> dict:
    return {
        "Full Name": f"{person['first_name']} {person['last_name']}" if random.random() > 0.05 else None,
        "Email": messy_email(person["email"]),
        "Phone": messy_phone(person["phone_digits"]),
        "Date": messy_created_at(person["created_at"]),
        "Ad ID": person["campaign_id"],
        "Opted In": "true" if person["consent"] else "false",
    }


def to_google_form_row(person: dict) -> dict:
    return {
        "Timestamp": messy_created_at(person["created_at"]),
        "First Name": person["first_name"] if random.random() > 0.05 else None,
        "Last Name": person["last_name"] if random.random() > 0.05 else None,
        "Email Address": messy_email(person["email"]),
        "Phone Number": messy_phone(person["phone_digits"]),
        "I agree to be contacted": "Yes" if person["consent"] else "No",
        "campaign": person["campaign_id"],
    }


def to_landing_page_record(person: dict) -> dict:
    return {
        "fname": person["first_name"] if random.random() > 0.05 else None,
        "lname": person["last_name"] if random.random() > 0.05 else None,
        "email": messy_email(person["email"]),
        "mobile": messy_phone(person["phone_digits"]),
        "consent": person["consent"],
        "ts": person["created_at"].isoformat(),
        "utm_campaign": person["campaign_id"],
    }


def duplicate_with_drift(person: dict) -> dict:
    """Same person submitting again -- formatting drifts slightly but it's
    still recognizably them, for the dedup engine to catch."""
    drifted = dict(person)
    if random.random() > 0.5:
        drifted["email"] = person["email"].upper()
    return drifted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=100_000, help="approx total raw submissions across all sources")
    parser.add_argument("--duplicate-rate", type=float, default=0.15)
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

    fb_payload = {"entry": [to_facebook_entry(p) for p in buckets["facebook"]]}
    (out_dir / "facebook_leads.json").write_text(json.dumps(fb_payload, indent=2))

    pd.DataFrame([to_instagram_row(p) for p in buckets["instagram"]]).to_csv(
        out_dir / "instagram_leads.csv", index=False
    )
    pd.DataFrame([to_google_form_row(p) for p in buckets["google_form"]]).to_csv(
        out_dir / "google_form_leads.csv", index=False
    )
    (out_dir / "landing_page_leads.json").write_text(
        json.dumps([to_landing_page_record(p) for p in buckets["landing_page"]], default=str, indent=2)
    )

    print(f"Generated {len(submissions)} raw submissions from {n_unique} unique people:")
    for source, records in buckets.items():
        print(f"  {source}: {len(records)} records -> {out_dir}/")


if __name__ == "__main__":
    main()
