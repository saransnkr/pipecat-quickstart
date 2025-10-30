"""Common configuration for the Google Calendar MCP server."""

from __future__ import annotations

import os
from pathlib import Path

# Base directory of the project (where google_secret.json lives by default)
BASE_DIR = Path(__file__).resolve().parent.parent

# Path to the OAuth client secret downloaded from Google Cloud.
DEFAULT_CREDENTIALS_PATH = Path(
    os.getenv("GOOGLE_OAUTH_CLIENT_FILE", BASE_DIR / "google_secret.json")
)

# Path where the server will store user OAuth tokens after authorization.
DEFAULT_TOKEN_PATH = Path(os.getenv("GOOGLE_OAUTH_TOKEN_FILE", BASE_DIR / "google_token.json"))

# OAuth scopes that the server needs.
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

# Port that the local OAuth helper listens on during authorization.
AUTH_REDIRECT_PORT = int(os.getenv("MCP_GOOGLE_CAL_AUTH_PORT", "8080"))

# Default host/port for the SSE (HTTP) transport the server exposes.
DEFAULT_HOST = os.getenv("MCP_GOOGLE_CAL_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MCP_GOOGLE_CAL_PORT", "9079"))
