# Sample data pack

~100,000 synthetic, messy leads across all 4 supported sources, generated
deterministically by `scripts/generate_data.py --seed 42 --total 100000`
(the default seed/total, so re-running that command reproduces this exact
pack byte-for-byte). This is the data the fresh-clone test and demo video
replay against.

| File | Source | Format |
|---|---|---|
| `facebook_leads.json` | Facebook Lead Ads | Nested webhook JSON (`entry[].changes[].value.field_data[]`) |
| `instagram_leads.csv` | Instagram lead ads export | Flat CSV: `Full Name, Email, Phone, Date, Ad ID, Opted In` |
| `google_form_leads.csv` | Google Forms export | Flat CSV: `Timestamp, First Name, Last Name, Email Address, Phone Number, I agree to be contacted, campaign` |
| `landing_page_leads.json` | Custom landing page | Flat JSON array: `fname, lname, email, mobile, consent, ts, utm_campaign` |

All four intentionally contain: inconsistent phone formatting (some
unparseable on purpose), malformed/missing emails, missing name/consent
fields, and cross-source duplicate people submitted more than once with
slightly different formatting each time -- see
`scripts/generate_data.py` for the exact messiness rules.

Regenerate with different parameters:

```bash
python -m scripts.generate_data --total 100000 --duplicate-rate 0.15 --seed 42 --out-dir data/sample_pack
```
