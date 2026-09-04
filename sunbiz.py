import json
import os
import smtplib
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage

import gspread
import requests
from google.oauth2.service_account import Credentials


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

API_BASE = "https://sunbizdaily.com/api/v2/filings/"

WORKSHEET_NAME = "Weekly Results"
LOG_SHEET_NAME = "Automation Log"

# Leave plenty of room below the API's 1,000/hour limit.
MAX_DETAIL_REQUESTS_PER_RUN = 700

# If the API says we are this close to the limit,
# stop safely and resume on the next scheduled run.
RATE_LIMIT_FLOOR = 75

OFFICIAL_SUNBIZ_LOOKUP = (
    "https://search.sunbiz.org/"
    "Inquiry/CorporationSearch/ByDocumentNumber"
)

HEADERS = [
    "Business Name",
    "Registration Date",
    "Source Date",
    "Business Address",
    "City",
    "County",
    "ZIP",
    "Entity Type",
    "Status",
    "Document Number",
    "Registered Agent",
    "Officer / Manager",
    "Sunbiz Link",
]

LOG_HEADERS = [
    "Week Start",
    "Week End",
    "Total Filings",
    "Completed",
    "Status",
    "Email Sent",
    "Last Updated",
]


# --------------------------------------------------
# ENVIRONMENT / CREDENTIALS
# --------------------------------------------------

def require_env(name):
    value = os.environ.get(name)

    if not value:
        raise ValueError(
            f"Required environment variable {name} is not set."
        )

    return value


def get_api_key():
    return require_env("SUNBIZ_API_KEY")


def get_spreadsheet_id():
    return require_env("SPREADSHEET_ID")


def get_google_credentials():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # GitHub version:
    service_json = os.environ.get(
        "GOOGLE_SERVICE_ACCOUNT_JSON"
    )

    if service_json:
        info = json.loads(service_json)

        return Credentials.from_service_account_info(
            info,
            scopes=scopes,
        )

    # Local-development version:
    return Credentials.from_service_account_file(
        "service-account.json",
        scopes=scopes,
    )


def get_google_spreadsheet():
    creds = get_google_credentials()

    client = gspread.authorize(creds)

    return client.open_by_key(
        get_spreadsheet_id()
    )


# --------------------------------------------------
# DATE RANGE
# --------------------------------------------------

def previous_week():
    today = date.today()

    this_monday = (
        today
        - timedelta(days=today.weekday())
    )

    previous_monday = (
        this_monday
        - timedelta(days=7)
    )

    previous_sunday = (
        this_monday
        - timedelta(days=1)
    )

    return (
        previous_monday.isoformat(),
        previous_sunday.isoformat(),
    )


# --------------------------------------------------
# GOOGLE SHEETS
# --------------------------------------------------

def get_or_create_worksheet(
    spreadsheet,
    name,
    rows=5000,
    cols=20,
):
    try:
        return spreadsheet.worksheet(name)

    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(
            title=name,
            rows=rows,
            cols=cols,
        )


def setup_results_sheet(sheet):
    current = sheet.row_values(1)

    if not current:
        sheet.update(
            range_name="A1:M1",
            values=[HEADERS],
        )

        return

    if current[:len(HEADERS)] != HEADERS:
        raise RuntimeError(
            "Weekly Results headers do not match "
            "the expected production layout."
        )


def setup_log_sheet(sheet):
    current = sheet.row_values(1)

    if not current:
        sheet.update(
            range_name="A1:G1",
            values=[LOG_HEADERS],
        )


def get_existing_document_numbers(sheet):
    values = sheet.col_values(10)

    if len(values) <= 1:
        return set()

    return {
        str(value).strip()
        for value in values[1:]
        if str(value).strip()
    }


def append_rows(sheet, rows):
    if not rows:
        return

    sheet.append_rows(
        rows,
        value_input_option="RAW",
    )


# --------------------------------------------------
# AUTOMATION LOG
# --------------------------------------------------

def get_week_log(log_sheet, start_date, end_date):
    records = log_sheet.get_all_records()

    for row_number, record in enumerate(
        records,
        start=2,
    ):
        if (
            str(record.get("Week Start")) == start_date
            and
            str(record.get("Week End")) == end_date
        ):
            return row_number, record

    return None, None


def update_week_log(
    log_sheet,
    start_date,
    end_date,
    total,
    completed,
    status,
    email_sent=False,
):
    row_number, existing = get_week_log(
        log_sheet,
        start_date,
        end_date,
    )

    timestamp = datetime.now().isoformat(
        timespec="seconds"
    )

    email_value = (
        "YES"
        if email_sent
        else (
            existing.get("Email Sent", "")
            if existing
            else ""
        )
    )

    row = [
        start_date,
        end_date,
        total,
        completed,
        status,
        email_value,
        timestamp,
    ]

    if row_number:
        log_sheet.update(
            range_name=f"A{row_number}:G{row_number}",
            values=[row],
        )

    else:
        log_sheet.append_row(
            row,
            value_input_option="RAW",
        )


def completion_email_already_sent(
    log_sheet,
    start_date,
    end_date,
):
    _, record = get_week_log(
        log_sheet,
        start_date,
        end_date,
    )

    if not record:
        return False

    return (
        str(
            record.get(
                "Email Sent",
                ""
            )
        ).upper()
        == "YES"
    )


# --------------------------------------------------
# SUNBIZ API
# --------------------------------------------------

def create_session():
    session = requests.Session()

    session.headers.update({
        "X-API-Key": get_api_key()
    })

    return session


def get_weekly_filings(
    session,
    start_date,
    end_date,
):
    print(
        f"\nFetching Miami-Dade filings "
        f"from {start_date} through {end_date}..."
    )

    page = 1
    all_filings = []

    while True:
        params = {
            "county": "Miami-Dade",
            "source_date_start": start_date,
            "source_date_end": end_date,
            "per_page": 100,
            "page": page,
        }

        response = session.get(
            API_BASE,
            params=params,
            timeout=60,
        )

        if response.status_code == 429:
            raise RuntimeError(
                "RATE_LIMIT"
            )

        response.raise_for_status()

        filings = (
            response.json().get(
                "filings",
                []
            )
        )

        all_filings.extend(
            filings
        )

        remaining = response.headers.get(
            "X-RateLimit-Remaining"
        )

        print(
            f"Page {page}: "
            f"{len(filings)} records "
            f"({len(all_filings)} total)"
            +
            (
                f" | API remaining: {remaining}"
                if remaining
                else ""
            )
        )

        if len(filings) < 100:
            break

        page += 1

    return all_filings


def get_detail(
    session,
    corporation_number,
):
    url = (
        API_BASE
        + corporation_number
        + "/"
    )

    for attempt in range(1, 4):
        try:
            response = session.get(
                url,
                timeout=45,
            )

            if response.status_code == 429:
                return None, "RATE_LIMIT", 0

            response.raise_for_status()

            remaining = response.headers.get(
                "X-RateLimit-Remaining"
            )

            remaining = (
                int(remaining)
                if remaining is not None
                else None
            )

            return (
                response.json(),
                None,
                remaining,
            )

        except requests.RequestException as error:
            if attempt == 3:
                return (
                    None,
                    str(error),
                    None,
                )

            time.sleep(
                attempt * 2
            )

    return None, "UNKNOWN", None


# --------------------------------------------------
# DATA FORMATTING
# --------------------------------------------------

def clean_name(value):
    if not value:
        return ""

    return " ".join(
        str(value).split()
    )


def format_address(address):
    if not address:
        return ""

    parts = [
        address.get("address_1"),
        address.get("address_2"),
        address.get("city"),
        address.get("state"),
        address.get("zip"),
    ]

    return ", ".join(
        str(part).strip()
        for part in parts
        if part
    )


def format_registered_agent(detail):
    agent = detail.get(
        "registered_agent"
    )

    if not agent:
        return ""

    return clean_name(
        agent.get("name")
    )


def format_officers(detail):
    officers = (
        detail.get("officers")
        or []
    )

    formatted = []

    for officer in officers:
        name = clean_name(
            officer.get("name")
        )

        title = (
            officer.get("title")
            or ""
        ).strip()

        if not name:
            continue

        if title:
            formatted.append(
                f"{name} ({title})"
            )

        else:
            formatted.append(name)

    return "; ".join(formatted)


def build_row(filing, detail):
    address = (
        detail.get(
            "principal_address"
        )
        or {}
    )

    return [
        filing.get(
            "corporation_name"
        ) or "",

        filing.get(
            "file_date"
        ) or "",

        filing.get(
            "source_date"
        ) or "",

        format_address(address),

        address.get("city")
        or filing.get("city")
        or "",

        filing.get("county")
        or "",

        address.get("zip")
        or filing.get("zip")
        or "",

        filing.get(
            "filing_type_display"
        ) or "",

        filing.get("status")
        or "",

        filing.get(
            "corporation_number"
        ) or "",

        format_registered_agent(
            detail
        ),

        format_officers(
            detail
        ),

        OFFICIAL_SUNBIZ_LOOKUP,
    ]


# --------------------------------------------------
# EMAIL
# --------------------------------------------------

def send_completion_email(
    start_date,
    end_date,
    total,
):
    gmail_address = require_env(
        "GMAIL_ADDRESS"
    )

    app_password = require_env(
        "GMAIL_APP_PASSWORD"
    )

    recipient = os.environ.get(
        "EMAIL_TO",
        gmail_address,
    )

    spreadsheet_url = (
        "https://docs.google.com/"
        "spreadsheets/d/"
        + get_spreadsheet_id()
        + "/edit"
    )

    message = EmailMessage()

    message["Subject"] = (
        f"Miami-Dade New Business "
        f"Registrations: {total}"
    )

    message["From"] = gmail_address
    message["To"] = recipient

    body = f"""
Miami-Dade weekly new-business registration update

Week:
{start_date} through {end_date}

New registrations:
{total}

The completed Google Sheet is available here:

{spreadsheet_url}

This report was generated automatically.
"""

    message.set_content(
        body.strip()
    )

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465,
    ) as smtp:

        smtp.login(
            gmail_address,
            app_password,
        )

        smtp.send_message(
            message
        )


# --------------------------------------------------
# MAIN AUTOMATION
# --------------------------------------------------

def main():
    print()
    print("==============================")
    print("SUNBIZ AUTOMATION START")
    print("==============================")

    start_date, end_date = (
        previous_week()
    )

    print(
        f"Target week: "
        f"{start_date} through {end_date}"
    )

    spreadsheet = (
        get_google_spreadsheet()
    )

    results_sheet = (
        get_or_create_worksheet(
            spreadsheet,
            WORKSHEET_NAME,
            rows=10000,
            cols=20,
        )
    )

    log_sheet = (
        get_or_create_worksheet(
            spreadsheet,
            LOG_SHEET_NAME,
            rows=500,
            cols=10,
        )
    )

    setup_results_sheet(
        results_sheet
    )

    setup_log_sheet(
        log_sheet
    )

    existing_ids = (
        get_existing_document_numbers(
            results_sheet
        )
    )

    print(
        f"Existing Sheet records: "
        f"{len(existing_ids)}"
    )

    session = create_session()

    try:
        filings = get_weekly_filings(
            session,
            start_date,
            end_date,
        )

    except RuntimeError as error:
        if str(error) == "RATE_LIMIT":
            print(
                "\nSunbiz API rate limit "
                "was already reached."
            )
            print(
                "No progress was lost. "
                "The next scheduled run "
                "can retry."
            )
            return

        raise

    weekly_ids = {
        str(
            filing.get(
                "corporation_number",
                ""
            )
        ).strip()
        for filing in filings
        if filing.get(
            "corporation_number"
        )
    }

    total_filings = len(
        weekly_ids
    )

    completed_before = len(
        weekly_ids
        & existing_ids
    )

    print(
        f"\nWeekly registrations: "
        f"{total_filings}"
    )

    print(
        f"Already completed: "
        f"{completed_before}"
    )

    # If this week is already complete,
    # do not waste detail API calls.
    if completed_before == total_filings:
        print(
            "\nThis week's data is "
            "already complete."
        )

        if not completion_email_already_sent(
            log_sheet,
            start_date,
            end_date,
        ):
            send_completion_email(
                start_date,
                end_date,
                total_filings,
            )

            update_week_log(
                log_sheet,
                start_date,
                end_date,
                total_filings,
                total_filings,
                "COMPLETE",
                email_sent=True,
            )

            print(
                "Completion email sent."
            )

        else:
            print(
                "Completion email was "
                "already sent."
            )

        return

    detail_requests_used = 0
    rows_to_append = []

    rate_limited = False

    for filing in filings:
        corporation_number = str(
            filing.get(
                "corporation_number",
                ""
            )
        ).strip()

        if not corporation_number:
            continue

        if corporation_number in existing_ids:
            continue

        if (
            detail_requests_used
            >= MAX_DETAIL_REQUESTS_PER_RUN
        ):
            print(
                "\nReached this run's "
                "detail-request safety limit."
            )
            break

        detail, error, remaining = (
            get_detail(
                session,
                corporation_number,
            )
        )

        if error == "RATE_LIMIT":
            print(
                "\nAPI rate limit reached."
            )
            rate_limited = True
            break

        if error:
            print(
                f"Detail failed for "
                f"{corporation_number}: "
                f"{error}"
            )
            continue

        detail_requests_used += 1

        row = build_row(
            filing,
            detail,
        )

        rows_to_append.append(
            row
        )

        existing_ids.add(
            corporation_number
        )

        # Write frequently so a crash loses
        # at most a small number of records.
        if len(rows_to_append) >= 25:
            append_rows(
                results_sheet,
                rows_to_append,
            )

            print(
                f"Saved 25 rows "
                f"| Detail requests: "
                f"{detail_requests_used}"
            )

            rows_to_append = []

        if (
            remaining is not None
            and
            remaining <= RATE_LIMIT_FLOOR
        ):
            print(
                "\nApproaching API rate limit. "
                "Stopping safely."
            )
            break

    if rows_to_append:
        append_rows(
            results_sheet,
            rows_to_append,
        )

        print(
            f"Saved final batch: "
            f"{len(rows_to_append)}"
        )

    completed_now = len(
        weekly_ids
        & existing_ids
    )

    print()
    print(
        f"Detail requests this run: "
        f"{detail_requests_used}"
    )

    print(
        f"Weekly completed: "
        f"{completed_now}/"
        f"{total_filings}"
    )

    if completed_now == total_filings:
        print(
            "\nWeekly dataset complete."
        )

        if not completion_email_already_sent(
            log_sheet,
            start_date,
            end_date,
        ):
            send_completion_email(
                start_date,
                end_date,
                total_filings,
            )

            update_week_log(
                log_sheet,
                start_date,
                end_date,
                total_filings,
                completed_now,
                "COMPLETE",
                email_sent=True,
            )

            print(
                "Completion email sent."
            )

    else:
        status = (
            "RATE LIMITED"
            if rate_limited
            else "IN PROGRESS"
        )

        update_week_log(
            log_sheet,
            start_date,
            end_date,
            total_filings,
            completed_now,
            status,
            email_sent=False,
        )

        print(
            "\nProgress saved. "
            "Next run will resume."
        )

    print()
    print("==============================")
    print("RUN COMPLETE")
    print("==============================")


if __name__ == "__main__":
    main()