import os
from pathlib import Path

from dotenv import load_dotenv


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv()


# =========================================================
# APPLICATION
# =========================================================

APP_NAME = os.getenv(
    "APP_NAME",
    "ClaimGuard"
)

APP_ENV = os.getenv(
    "APP_ENV",
    "development"
)


# =========================================================
# JWT
# =========================================================

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "change-this-development-secret"
)

ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv(
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        "60"
    )
)


# =========================================================
# GMAIL SMTP
# =========================================================

SMTP_HOST = os.getenv(
    "SMTP_HOST",
    "smtp.gmail.com"
)

SMTP_PORT = int(
    os.getenv(
        "SMTP_PORT",
        "465"
    )
)

EMAIL_USER = os.getenv(
    "EMAIL_USER",
    ""
)

EMAIL_APP_PASSWORD = os.getenv(
    "EMAIL_APP_PASSWORD",
    ""
)