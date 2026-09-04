import os
import smtplib
from email.message import EmailMessage


gmail_address = os.environ.get("GMAIL_ADDRESS")
app_password = os.environ.get("GMAIL_APP_PASSWORD")

if not gmail_address:
    raise ValueError("GMAIL_ADDRESS is not set.")

if not app_password:
    raise ValueError("GMAIL_APP_PASSWORD is not set.")


message = EmailMessage()

message["Subject"] = "Sunbiz Automation Test"
message["From"] = gmail_address
message["To"] = gmail_address

message.set_content(
    """Sunbiz automation email test successful.

If you received this message, Python can successfully send the weekly Sunbiz notification through Gmail.
"""
)


with smtplib.SMTP_SSL(
    "smtp.gmail.com",
    465
) as smtp:

    smtp.login(
        gmail_address,
        app_password
    )

    smtp.send_message(message)


print("SUCCESS!")
print("Test email sent.")