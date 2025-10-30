"""OAuth credential management for the Google Calendar MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


class AuthorizationRequiredError(RuntimeError):
    """Raised when the user must complete the OAuth flow before continuing."""


class CredentialConfigurationError(RuntimeError):
    """Raised when the client credentials file is missing or malformed."""


def _ensure_file_exists(path: Path, error_cls: type[Exception]) -> None:
    if not path.exists():
        raise error_cls(f"Missing file: {path}. Please ensure the path is correct.")


@dataclass(slots=True)
class OAuthPaths:
    """Holds the locations of the OAuth client secret and stored token."""

    client_secret: Path
    token_store: Path


class GoogleOAuthManager:
    """Helper that loads and refreshes OAuth credentials on demand."""

    def __init__(self, paths: OAuthPaths, scopes: Iterable[str], redirect_port: int) -> None:
        self._paths = paths
        self._scopes = list(scopes)
        self._redirect_port = redirect_port

    @property
    def paths(self) -> OAuthPaths:
        return self._paths

    def get_credentials(self, *, interactive: bool = False) -> Credentials:
        """
        Load OAuth credentials, refreshing or prompting the user if required.

        Args:
            interactive: When True and the stored token is absent or invalid, a local
                browser flow is started so the user can authorize the application.

        Raises:
            AuthorizationRequiredError: If interactive is False but authorization is needed.
            CredentialConfigurationError: If the client secret cannot be found.
        """

        _ensure_file_exists(self._paths.client_secret, CredentialConfigurationError)

        creds: Credentials | None = None
        if self._paths.token_store.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._paths.token_store), self._scopes
            )

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                # Token is no longer valid; require a new interactive grant.
                creds = None
                if not interactive:
                    raise AuthorizationRequiredError(
                        "Stored Google OAuth token can no longer be refreshed. "
                        "Run the authorization helper to re-authorize."
                    ) from exc

        if creds is None:
            if not interactive:
                raise AuthorizationRequiredError(
                    "No Google OAuth token found. Please run the authorization helper "
                    "to sign in with your Google account."
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(self._paths.client_secret), self._scopes
            )
            creds = flow.run_local_server(
                host="localhost",
                port=self._redirect_port,
                authorization_prompt_message="Authorize access to Google Calendar",
                success_message="Authorization completed. You may close this tab.",
            )
            self._paths.token_store.write_text(creds.to_json(), encoding="utf-8")

        return creds


def run_interactive_authorization(paths: OAuthPaths, scopes: Iterable[str], redirect_port: int) -> None:
    """Convenience helper so users can authorize without importing the class manually."""
    manager = GoogleOAuthManager(paths, scopes, redirect_port)
    manager.get_credentials(interactive=True)
