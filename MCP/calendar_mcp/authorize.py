"""Command-line entry point to complete the Google OAuth flow."""

from __future__ import annotations

from .auth import OAuthPaths, run_interactive_authorization
from .config import (
    AUTH_REDIRECT_PORT,
    CALENDAR_SCOPES,
    DEFAULT_CREDENTIALS_PATH,
    DEFAULT_TOKEN_PATH,
)


def main() -> None:
    run_interactive_authorization(
        OAuthPaths(
            client_secret=DEFAULT_CREDENTIALS_PATH,
            token_store=DEFAULT_TOKEN_PATH,
        ),
        CALENDAR_SCOPES,
        AUTH_REDIRECT_PORT,
    )


if __name__ == "__main__":
    main()
