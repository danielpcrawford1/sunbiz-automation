# Sunbiz Automation

Monitor new Miami-Dade business registrations each week without rebuilding a lead list by hand. This Python script pulls filings from the Sunbiz Daily API (a third-party feed of Florida Sunbiz corporation records), adds only registrations not already in a Google Sheet, records the run's progress, and emails a completion summary when the week's data is complete.

## How it works

1. `sunbiz.py` requests filings for the previous Monday–Sunday period from `https://sunbizdaily.com/api/v2/filings/`, filtered to Miami-Dade. It fetches details for filings it has not already processed.
2. It reads document numbers already in column 10 of the **Weekly Results** worksheet and skips matches. New rows go into that worksheet, so a subsequent run can resume without adding the same document number again.
3. The **Automation Log** worksheet records week start and end, total filings, completed count, status, whether the completion email was sent, and last-updated time.
4. When the weekly set is complete, the script emails a summary and a link to the spreadsheet. The repository includes a GitHub Actions workflow (`.github/workflows/sunbiz.yml`) intended to run on Mondays, but its schedule configuration needs correction and a successful scheduled-run check before claiming it runs automatically. Manual dispatch is configured too.

Each result row contains: Business Name, Registration Date, Source Date, Business Address, City, County, ZIP, Entity Type, Status, Document Number, Registered Agent, Officer / Manager, and Sunbiz Link.

## Setup

Requires Python, a Sunbiz Daily API key, a Google Sheet accessible to a Google service account, and a Gmail account configured for the completion email. Install dependencies with:

```bash
python -m pip install -r requirements.txt
```

Set these environment variables before running `python sunbiz.py`:

| Variable | Purpose |
|---|---|
| `SUNBIZ_API_KEY` | API key for the third-party Sunbiz Daily feed. |
| `SPREADSHEET_ID` | Exact ID of the destination Google Sheet, supplied by its owner. |
| `GMAIL_ADDRESS` | Sender address for the completion email. |
| `GMAIL_APP_PASSWORD` | Gmail app password used by the script to send mail. |
| `EMAIL_TO` | Optional recipient; defaults to `GMAIL_ADDRESS` if unset. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full service-account JSON supplied as an environment variable for the GitHub Actions path. For local development, if this is unset, the script reads `service-account.json` from its working directory. |

Give the service account access to the chosen Sheet before running. The script creates **Weekly Results** and **Automation Log** worksheets if they do not exist; it checks the existing results header layout before writing. Keep API keys, app passwords, service-account JSON, and spreadsheet identifiers out of commits and issue text. For GitHub Actions, set the five required values as repository secrets with the names shown above; `EMAIL_TO` is optional in the Python script and is not set by the checked-in workflow. For local use, supply the variables securely in your environment and keep `service-account.json` out of version control. Do not commit real credentials.

Run locally:

```bash
python sunbiz.py
```

`test_google.py` and `test_email.py` are separate integration-check scripts; they are not a substitute for reviewing a real run's **Automation Log** and output rows.

## Rate-limit and restart behavior

The script caps detail lookups at **700 per run** and watches the API's remaining-request header. If a detail response reports **75 or fewer** requests remaining, or the API returns a rate-limit response, it stops adding new detail requests, saves collected rows and progress, and leaves the week marked incomplete. If the run stops partway, a later run can use document numbers already in **Weekly Results** to skip completed filings and continue. The completion email is sent when the week's dataset is complete, not after each partial run. The current Actions schedule must be repaired and tested; until then, a later run requires manual dispatch or another scheduler.

This repository uses `requests`, `gspread`, and `google-auth` (see `requirements.txt`). The API feed is third-party; the official Sunbiz site is linked in output for lookup, but the script does not scrape that site directly.
