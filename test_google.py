import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = Credentials.from_service_account_file(
    "service-account.json",
    scopes=SCOPES,
)

client = gspread.authorize(creds)

# Change this ONLY if your Google Sheet has a different name
spreadsheet = client.open_by_key("1ZiiUwRoBMnqS7Sg2gchosNciEIDnRHi4Jtr3T0V_On8")

sheet = spreadsheet.worksheet("Python Test")

sheet.update(
    range_name="A1:B3",
    values=[
        ["Test", "Status"],
        ["Python", "Connected"],
        ["Google Sheets", "Working"],
    ],
)

print("SUCCESS!")
print("Python successfully wrote to Google Sheets.")