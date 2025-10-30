"""High-level helpers that wrap the Google Calendar API."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .auth import AuthorizationRequiredError, GoogleOAuthManager


class GoogleCalendarError(RuntimeError):
    """Raised for recoverable Google Calendar API issues."""


class GoogleCalendarService:
    """Thin wrapper around the Google Calendar REST API."""

    def __init__(self, oauth_manager: GoogleOAuthManager) -> None:
        self._oauth_manager = oauth_manager

    def list_calendars(self) -> list[Mapping[str, Any]]:
        service = self._build_service()
        response = service.calendarList().list(showDeleted=False).execute()
        return response.get("items", [])

    def list_events(
        self,
        *,
        calendar_id: str,
        max_results: int,
        time_min: datetime | None,
        time_max: datetime | None,
        query: str | None,
        single_events: bool = True,
        order_by_start_time: bool = True,
    ) -> list[Mapping[str, Any]]:
        service = self._build_service()
        request_kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "maxResults": max_results,
            "singleEvents": single_events,
        }
        if time_min:
            request_kwargs["timeMin"] = to_rfc3339(time_min)
        if time_max:
            request_kwargs["timeMax"] = to_rfc3339(time_max)
        if query:
            request_kwargs["q"] = query
        if order_by_start_time:
            request_kwargs["orderBy"] = "startTime"

        response = service.events().list(**request_kwargs).execute()
        return response.get("items", [])

    def create_event(
        self,
        *,
        calendar_id: str,
        body: Mapping[str, Any],
        conference_data_version: int | None = None,
    ) -> Mapping[str, Any]:
        service = self._build_service()
        kwargs: dict[str, Any] = {"calendarId": calendar_id, "body": dict(body)}
        if conference_data_version is not None:
            kwargs["conferenceDataVersion"] = conference_data_version
        return service.events().insert(**kwargs).execute()

    def update_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        body: Mapping[str, Any],
        conference_data_version: int | None = None,
    ) -> Mapping[str, Any]:
        service = self._build_service()
        kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "eventId": event_id,
            "body": dict(body),
        }
        if conference_data_version is not None:
            kwargs["conferenceDataVersion"] = conference_data_version
        return service.events().patch(**kwargs).execute()

    def delete_event(self, *, calendar_id: str, event_id: str) -> None:
        service = self._build_service()
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    def _build_service(self):
        credentials = self._oauth_manager.get_credentials(interactive=False)
        try:
            return build(
                "calendar",
                "v3",
                credentials=credentials,
                cache_discovery=False,
            )
        except HttpError as exc:
            raise GoogleCalendarError(str(exc)) from exc


def to_rfc3339(value: datetime) -> str:
    """Ensure a datetime is timezone aware and convert to RFC3339."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_get(dictionary: Mapping[str, Any], path: Iterable[str]) -> Any | None:
    """Traverse a nested dictionary gracefully."""
    current: Any = dictionary
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def extract_event_times(event: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Return ISO strings for the start and end values if present."""
    for key in ("start", "end"):
        if key not in event:
            continue
        entry = event[key]
        if isinstance(entry, Mapping):
            with contextlib.suppress(KeyError):
                event[key] = entry.get("dateTime") or entry.get("date")
    start = (
        event["start"]
        if isinstance(event.get("start"), str)
        else safe_get(event, ("start", "dateTime"))
    )
    end = (
        event["end"]
        if isinstance(event.get("end"), str)
        else safe_get(event, ("end", "dateTime"))
    )
    return start, end
