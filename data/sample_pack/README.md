# Sample data pack

~100,000 synthetic, messy leads across all 4 supported sources, generated
deterministically by `scripts/generate_data.py --seed 42 --total 100000`
(the default seed/total, so re-running that command reproduces this exact
pack byte-for-byte). This is the data the fresh-clone test and demo video
replay against. File names, formats, and the messiness rules below match
the team's official sample-data spec.

| File | Source | Format |
|---|---|---|
| `facebook_leads.jsonl` | Facebook Lead Ads | JSONL -- one complete webhook delivery per line (`entry[].changes[].value.field_data[]`) |
| `instagram_export.csv` | Instagram Ads Manager export | Flat CSV: `Full Name, E-mail, Phone #, Date, Ad ID, Opted In` |
| `google_form.csv` | Google Forms export | Flat CSV, question-style headers: `Timestamp, What's your name?, Your email address, Best number to reach you, Do you agree to be contacted?, How did you hear about us?` |
| `landing_page.jsonl` | Custom landing page | JSONL -- one lead per line: `fname, lname, email_addr, mobile, opt_in, utm_campaign, utm_source, ts` |

Intentional mess baked into every file (see `scripts/generate_data.py` for
the exact rules):

- **Phone numbers in 7+ formats**: `+1 (555) 123-4567`, `555-123-4567`,
  `5551234567`, `1-555-123-4567`, and pure junk (`12345`, `N/A`,
  `000-000-0000`)
- **Junk/typo emails**: `test@test.com`, `asdf@asdf` (malformed, no TLD),
  `name@gmial.com` (typo domain -- corrected in cleaning, not rejected,
  since it's a real person's real mistake)
- **~25% of people appear in more than one source** (cross-source
  duplicates, with slightly different formatting each time)
- **Missing fields**, dropped randomly (especially from Facebook
  `field_data` and the landing page)
- **Mixed date formats**: Unix epoch, ISO 8601, `MM/DD/YYYY hh:mm AM`,
  `DD-Mon-YYYY`
- **Every common consent encoding**: `Yes/yes/Y/TRUE/I agree/empty/boolean`
- **ALL-CAPS names, emoji in names, and empty rows**

Regenerate with different parameters:

```bash
python -m scripts.generate_data --total 100000 --duplicate-rate 0.25 --seed 42 --out-dir data/sample_pack
```
