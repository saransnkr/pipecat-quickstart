"""Pydantic models shared by the MCP tools."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, validator


def _ensure_timezone(value: datetime) -> datetime:
    """Default naive datetimes to UTC so Google accepts them."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class EventTime(BaseModel):
    """Represents a single event boundary."""

    value: datetime = Field(
        description="ISO8601 timestamp. Naive values are assumed to be in UTC."
    )
    time_zone: str | None = Field(
        default=None,
        description=(
            "Optional IANA timezone identifier (e.g. 'America/New_York'). "
            "When omitted, the timezone from the timestamp is used."
        ),
    )

    @validator("value", pre=True)
    def parse_datetime(cls, value: Any) -> Any:
        if isinstance(value, str) and value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return value

    def to_google(self) -> dict[str, str]:
        value = _ensure_timezone(self.value)
        iso_value = value.isoformat()
        payload = {"dateTime": iso_value}
        if self.time_zone:
            payload["timeZone"] = self.time_zone
        return payload


class Attendee(BaseModel):
    email: str = Field(description="Email address of the attendee.")
    optional: bool = Field(
        default=False,
        description="Set true for optional attendees. Defaults to false.",
    )

    def to_google(self) -> dict[str, Any]:
        return {"email": self.email, "optional": self.optional}


class ListEventsInput(BaseModel):
    calendar_id: str = Field(
        default="primary",
        description="Calendar identifier or 'primary' for the signed-in user.",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=2500,
        description="Maximum number of events to return (Google allows up to 2500).",
    )
    time_min: datetime | None = Field(
        default=None,
        description="Earliest event start to include (ISO8601). Defaults to now.",
    )
    time_max: datetime | None = Field(
        default=None,
        description="Latest event start to include (ISO8601). Optional.",
    )
    query: str | None = Field(
        default=None,
        description="Full-text search query applied to the event metadata.",
    )

    @validator("time_min", "time_max", pre=True)
    def adjust_times(cls, value: Any) -> Any:
        if isinstance(value, str) and value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return value


class CreateEventInput(BaseModel):
    calendar_id: str = Field(default="primary")
    summary: str = Field(description="Human-readable title for the event.")
    description: str | None = Field(default=None, description="Optional description.")
    location: str | None = Field(default=None, description="Physical or virtual location.")
    start: EventTime = Field(description="Start timestamp for the event.")
    end: EventTime = Field(description="End timestamp for the event.")
    attendees: list[Attendee] | None = Field(
        default=None, description="Optional list of attendees."
    )
    conference_solution: bool = Field(
        default=False,
        description="Set true to request a Google Meet link when supported.",
    )


class UpdateEventInput(BaseModel):
    calendar_id: str = Field(default="primary")
    event_id: str = Field(description="Identifier of the event to update.")
    summary: str | None = None
    description: str | None = None
    location: str | None = None
    start: EventTime | None = None
    end: EventTime | None = None
    attendees: list[Attendee] | None = None
    conference_solution: bool | None = None


class DeleteEventInput(BaseModel):
    calendar_id: str = Field(default="primary")
    event_id: str = Field(description="Identifier of the event to delete.")


class EventOutput(BaseModel):
    id: str
    summary: str | None = None
    description: str | None = None
    location: str | None = None
    start: str | None = None
    end: str | None = None
    status: str | None = None
    html_link: str | None = Field(default=None, alias="htmlLink")
    hangout_link: str | None = Field(default=None, alias="hangoutLink")
    updated: str | None = None
    organizer: dict[str, Any] | None = None

    class Config:
        populate_by_name = True


class CalendarSummary(BaseModel):
    id: str
    summary: str
    description: str | None = None
    primary: bool | None = None
    time_zone: str | None = Field(default=None, alias="timeZone")
    access_role: str | None = Field(default=None, alias="accessRole")

    class Config:
        populate_by_name = True


class DeleteEventResult(BaseModel):
    deleted: bool = Field(default=True, description="Indicates the event was deleted.")
    event_id: str = Field(description="Identifier of the deleted event.")
    calendar_id: str = Field(description="Calendar from which the event was removed.")
