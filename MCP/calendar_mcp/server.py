"""Definition of the Google Calendar MCP server."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from googleapiclient.errors import HttpError
from mcp.server.fastmcp import Context, FastMCP

from .auth import AuthorizationRequiredError, GoogleOAuthManager, OAuthPaths
from .calendar_service import (
    GoogleCalendarError,
    GoogleCalendarService,
    extract_event_times,
)
from .config import (
    AUTH_REDIRECT_PORT,
    CALENDAR_SCOPES,
    DEFAULT_CREDENTIALS_PATH,
    DEFAULT_TOKEN_PATH,
)
from .models import (
    Attendee,
    CalendarSummary,
    DeleteEventResult,
    EventOutput,
    EventTime,
)

AUTH_HELP = (
    "Google authorization is required. Run `python -m calendar_mcp.authorize` "
    "from this project directory, complete the browser sign-in, then retry the tool."
)


paths = OAuthPaths(
    client_secret=DEFAULT_CREDENTIALS_PATH,
    token_store=DEFAULT_TOKEN_PATH,
)
oauth_manager = GoogleOAuthManager(paths, CALENDAR_SCOPES, AUTH_REDIRECT_PORT)
calendar_api = GoogleCalendarService(oauth_manager)

calendar_server = FastMCP(
    "google-calendar",
    instructions=(
        "Tools that let you browse, create, update, and delete Google Calendar events "
        "for the authorized Google account. If an authorization error occurs, ask the "
        "user to run `python -m calendar_mcp.authorize` locally and retry."
    ),
    website_url="https://calendar.google.com",
)


def _normalize_event_payload(event: dict[str, Any]) -> EventOutput:
    copy = dict(event)
    start, end = extract_event_times(copy)
    if start:
        copy["start"] = start
    if end:
        copy["end"] = end
    return EventOutput.model_validate(copy)


def _handle_calendar_exception(exc: Exception) -> RuntimeError:
    if isinstance(exc, AuthorizationRequiredError):
        return RuntimeError(AUTH_HELP)
    if isinstance(exc, HttpError):
        return RuntimeError(f"Google Calendar API error: {exc}")
    if isinstance(exc, GoogleCalendarError):
        return RuntimeError(str(exc))
    return RuntimeError(f"Unexpected error: {exc}")  # Fallback


def _ensure_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@calendar_server.tool(
    description="List upcoming events in a Google Calendar.",
    structured_output=True,
)
def list_events(
    calendar_id: str = "primary",
    max_results: int = 10,
    time_min: datetime | None = None,
    time_max: datetime | None = None,
    query: str | None = None,
    ctx: Context | None = None,
) -> list[EventOutput]:
    """
    Return up to ``max_results`` events ordered by start time.

    Args:
        calendar_id: Target calendar identifier, or ``primary`` for the signed-in user.
        max_results: Maximum number of events to return (Google allows up to 2500).
        time_min: Lower bound (inclusive) for an event's start time, defaults to now.
        time_max: Upper bound (exclusive) for an event's start time.
        query: Optional free-text search query.
    """
    time_min = _ensure_time(time_min) or datetime.now(timezone.utc)
    time_max = _ensure_time(time_max)

    try:
        events = calendar_api.list_events(
            calendar_id=calendar_id,
            max_results=max_results,
            time_min=time_min,
            time_max=time_max,
            query=query,
        )
    except Exception as exc:  # noqa: BLE001 - unified error handling
        raise _handle_calendar_exception(exc) from exc

    normalized = [_normalize_event_payload(event) for event in events]
    if ctx:
        ctx.info(f"Fetched {len(normalized)} events from calendar '{calendar_id}'.")
    return normalized


@calendar_server.tool(
    description="Create a new Google Calendar event.",
    structured_output=True,
)
def create_event(
    summary: str,
    start: EventTime,
    end: EventTime,
    calendar_id: str = "primary",
    description: str | None = None,
    location: str | None = None,
    attendees: list[Attendee] | None = None,
    conference_solution: bool = False,
    ctx: Context | None = None,
) -> EventOutput:
    body: dict[str, Any] = {
        "summary": summary,
        "start": start.to_google(),
        "end": end.to_google(),
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [attendee.to_google() for attendee in attendees]

    conference_data_version: int | None = None
    if conference_solution:
        conference_data_version = 1
        body["conferenceData"] = {
            "createRequest": {
                "requestId": f"mcp-{uuid4().hex}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    try:
        created = calendar_api.create_event(
            calendar_id=calendar_id,
            body=body,
            conference_data_version=conference_data_version,
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle_calendar_exception(exc) from exc

    result = _normalize_event_payload(created)
    if ctx:
        ctx.info(f"Created event '{result.id}' in calendar '{calendar_id}'.")
    return result


@calendar_server.tool(
    description="Update an existing Google Calendar event.",
    structured_output=True,
)
def update_event(
    event_id: str,
    calendar_id: str = "primary",
    summary: str | None = None,
    description: str | None = None,
    location: str | None = None,
    start: EventTime | None = None,
    end: EventTime | None = None,
    attendees: list[Attendee] | None = None,
    conference_solution: bool | None = None,
    ctx: Context | None = None,
) -> EventOutput:
    body: dict[str, Any] = {}
    if summary is not None:
        body["summary"] = summary
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location
    if start is not None:
        body["start"] = start.to_google()
    if end is not None:
        body["end"] = end.to_google()
    if attendees is not None:
        body["attendees"] = [attendee.to_google() for attendee in attendees]

    conference_data_version: int | None = None
    if conference_solution is True:
        conference_data_version = 1
        body["conferenceData"] = {
            "createRequest": {
                "requestId": f"mcp-{uuid4().hex}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    # When explicitly False we skip modifications to conference data. Removing
    # existing conferences requires more nuanced handling; for now we leave the
    # event as-is unless a new link is requested.

    if not body:
        raise RuntimeError("No updates were provided.")

    try:
        updated = calendar_api.update_event(
            calendar_id=calendar_id,
            event_id=event_id,
            body=body,
            conference_data_version=conference_data_version,
        )
    except Exception as exc:  # noqa: BLE001
        raise _handle_calendar_exception(exc) from exc

    result = _normalize_event_payload(updated)
    if ctx:
        ctx.info(f"Updated event '{event_id}' in calendar '{calendar_id}'.")
    return result


@calendar_server.tool(
    description="Delete a Google Calendar event.",
    structured_output=True,
)
def delete_event(
    event_id: str,
    calendar_id: str = "primary",
    ctx: Context | None = None,
) -> DeleteEventResult:
    try:
        calendar_api.delete_event(calendar_id=calendar_id, event_id=event_id)
    except Exception as exc:  # noqa: BLE001
        raise _handle_calendar_exception(exc) from exc

    if ctx:
        ctx.info(f"Deleted event '{event_id}' from calendar '{calendar_id}'.")
    return DeleteEventResult(event_id=event_id, calendar_id=calendar_id)


@calendar_server.tool(
    description="List calendars visible to the authorized Google account.",
    structured_output=True,
)
def list_calendars(ctx: Context | None = None) -> list[CalendarSummary]:
    try:
        calendars = calendar_api.list_calendars()
    except Exception as exc:  # noqa: BLE001
        raise _handle_calendar_exception(exc) from exc

    summaries = [CalendarSummary.model_validate(cal) for cal in calendars]
    if ctx:
        ctx.info(f"Found {len(summaries)} calendars.")
    return summaries


def create_app():
    """Return a Starlette app that exposes the MCP server via SSE transport."""
    return calendar_server.sse_app()
