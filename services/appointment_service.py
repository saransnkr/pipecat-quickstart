import asyncio
import json
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, time as time_cls
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from loguru import logger
from zoneinfo import ZoneInfo

from mcp import types as mcp_types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.shared.exceptions import McpError


@dataclass(frozen=True)
class Slot:
    """Represents a computed appointment slot."""

    slot_id: str
    start: datetime
    end: datetime
    timezone: ZoneInfo

    @property
    def label(self) -> str:
        start_display = self.start.astimezone(self.timezone).strftime("%I:%M %p")
        end_display = self.end.astimezone(self.timezone).strftime("%I:%M %p")
        return f"{start_display} - {end_display}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.slot_id,
            "label": self.label,
            "start_time": self.start.isoformat(),
            "end_time": self.end.isoformat(),
            "timezone": self.timezone.key,
        }


class AppointmentService:
    """Google Calendar appointment helper backed by an MCP server."""

    def __init__(
        self,
        *,
        server_url: str,
        calendar_id: str = "primary",
        timezone: str = "UTC",
        default_duration_minutes: int = 30,
        api_key: str | None = None,
        timeout: float = 10.0,
        workday_start: str | None = None,
        workday_end: str | None = None,
    ):
        base_url = server_url.rstrip("/")
        if base_url.lower().endswith("/sse"):
            self._server_url = base_url
            self._sse_endpoint = base_url
        else:
            self._server_url = base_url
            self._sse_endpoint = f"{base_url}/sse"
        self._calendar_id = calendar_id or "primary"
        self._timezone = ZoneInfo(timezone)
        self._slot_duration = timedelta(minutes=max(1, default_duration_minutes))
        self._timeout = timeout

        self._workday_start = self._parse_time(workday_start) if workday_start else time_cls(9, 0)
        self._workday_end = self._parse_time(workday_end) if workday_end else time_cls(17, 0)

        # If end earlier than start, wrap to default end of day.
        reference_day = datetime.now().date()
        if datetime.combine(reference_day, self._workday_end) <= datetime.combine(reference_day, self._workday_start):
            self._workday_end = time_cls(23, 59)

        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else None

        self._session_lock = asyncio.Lock()
        self._session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None

    async def _ensure_session(self) -> ClientSession:
        async with self._session_lock:
            if self._session is not None:
                return self._session

            exit_stack = AsyncExitStack()
            await exit_stack.__aenter__()

            try:
                read_stream, write_stream = await exit_stack.enter_async_context(
                    sse_client(
                        self._sse_endpoint,
                        headers=self._headers,
                        timeout=self._timeout,
                    )
                )

                session = ClientSession(read_stream, write_stream)
                session = await exit_stack.enter_async_context(session)
                await session.initialize()
            except Exception:
                await exit_stack.aclose()
                raise

            self._exit_stack = exit_stack
            self._session = session
            return session

    async def _call_tool(self, name: str, arguments: Mapping[str, Any]) -> mcp_types.CallToolResult:
        try:
            session = await self._ensure_session()
            result = await session.call_tool(name, dict(arguments))
        except McpError as exc:
            logger.error(f"MCP tool '{name}' failed: {exc}")
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:
            logger.exception(f"Unexpected error calling MCP tool '{name}'")
            raise RuntimeError(str(exc)) from exc

        if result.isError:
            message = self._extract_text(result.content) or f"MCP tool '{name}' returned an error."
            logger.error(message)
            raise RuntimeError(message)

        return result

    async def fetch_slots(self, filters: Mapping[str, Any]) -> Dict[str, Any]:
        """Compute available slots for a specific date."""
        requested_date = filters.get("date")
        if not requested_date:
            return {"success": False, "error": "Missing required 'date' parameter."}

        try:
            day = datetime.fromisoformat(requested_date).date()
        except ValueError:
            return {"success": False, "error": "Invalid 'date' format. Use YYYY-MM-DD."}

        day_start, day_end = self._day_boundaries(day)

        try:
            events, busy_intervals = await self._list_events(day_start, day_end)
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

        slots = self._generate_slots(day_start, day_end, busy_intervals)

        return {
            "success": True,
            "slots": [slot.as_dict() for slot in slots],
            "raw": {"events": events},
        }

    async def check_availability(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Check whether a specific slot remains free."""
        slot_id = payload.get("slot_id")
        slot_start_str = payload.get("date") or payload.get("start_time")
        slot_end_str = payload.get("end_time")

        if slot_start_str is None:
            return {"success": False, "error": "Missing slot start time."}

        start_dt = self._parse_datetime(slot_start_str)
        if start_dt is None:
            return {"success": False, "error": "Could not parse slot start time."}

        end_dt = self._parse_datetime(slot_end_str) if slot_end_str else start_dt + self._slot_duration
        if end_dt is None:
            return {"success": False, "error": "Could not determine slot end time."}

        day_start, day_end = self._day_boundaries(start_dt.date())

        try:
            _, busy_intervals = await self._list_events(day_start, day_end)
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

        conflict = self._has_conflict(start_dt, end_dt, busy_intervals)

        message_parts = []
        if slot_id:
            message_parts.append(f"Slot {slot_id}")
        message_parts.append("is available." if not conflict else "is no longer available.")

        return {
            "success": True,
            "available": not conflict,
            "message": " ".join(message_parts),
        }

    async def book_slot(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Create a calendar event for the selected slot."""
        slot_start_str = payload.get("date") or payload.get("start_time")
        slot_end_str = payload.get("end_time")
        if slot_start_str is None:
            return {"success": False, "error": "Missing slot start time."}

        start_dt = self._parse_datetime(slot_start_str)
        if start_dt is None:
            return {"success": False, "error": "Invalid slot start time."}

        end_dt = self._parse_datetime(slot_end_str) if slot_end_str else start_dt + self._slot_duration
        if end_dt is None:
            return {"success": False, "error": "Invalid slot end time."}

        patient_name = payload.get("patient_name") or payload.get("name")
        patient_phone = payload.get("patient_phone") or payload.get("phone")
        doctor = payload.get("doctor")
        notes = payload.get("notes")
        patient_email = payload.get("patient_email") or payload.get("email")

        if not patient_name or not patient_phone:
            return {"success": False, "error": "Patient name and phone number are required."}

        day_start, day_end = self._day_boundaries(start_dt.date())

        try:
            _, busy_intervals = await self._list_events(day_start, day_end)
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

        if self._has_conflict(start_dt, end_dt, busy_intervals):
            return {
                "success": False,
                "error": "The selected time is no longer available.",
            }

        summary = f"Appointment with {patient_name}"
        if doctor:
            summary = f"{doctor} - {summary}"

        description_lines = [f"Patient phone: {patient_phone}"]
        if notes:
            description_lines.append(f"Notes: {notes}")
        description = "\n".join(description_lines)

        attendees = [{"email": patient_email, "optional": False}] if patient_email else None

        args: Dict[str, Any] = {
            "calendar_id": self._calendar_id,
            "summary": summary,
            "description": description,
            "start": {
                "value": start_dt.isoformat(),
                "time_zone": self._timezone.key,
            },
            "end": {
                "value": end_dt.isoformat(),
                "time_zone": self._timezone.key,
            },
        }
        if attendees:
            args["attendees"] = attendees

        try:
            result = await self._call_tool("create_event", args)
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

        structured = self._extract_structured(result)
        event_id = None
        if isinstance(structured, Mapping):
            event_id = structured.get("id")

        message = f"Appointment booked for {patient_name} at {start_dt.astimezone(self._timezone).strftime('%I:%M %p')}."

        return {
            "success": True,
            "event_id": event_id,
            "message": message,
            "raw": structured,
        }

    async def aclose(self):
        """Close the MCP session if it is open."""
        async with self._session_lock:
            session = self._session
            exit_stack = self._exit_stack

            self._session = None
            self._exit_stack = None

        if exit_stack:
            await exit_stack.aclose()
        elif session:
            await session.__aexit__(None, None, None)

    async def _list_events(self, time_min: datetime, time_max: datetime) -> Tuple[List[Mapping[str, Any]], List[Tuple[datetime, datetime]]]:
        result = await self._call_tool(
            "list_events",
            {
                "calendar_id": self._calendar_id,
                "time_min": time_min.isoformat(),
                "time_max": time_max.isoformat(),
                "max_results": 250,
            },
        )

        structured = self._extract_structured(result)
        events: Sequence[Mapping[str, Any]] = []
        if isinstance(structured, list):
            events = structured  # type: ignore[assignment]
        elif isinstance(structured, tuple):
            events = list(structured)  # type: ignore[assignment]
        elif isinstance(structured, Mapping):
            maybe_events = structured.get("result")
            if isinstance(maybe_events, list):
                events = maybe_events  # type: ignore[assignment]
            elif isinstance(maybe_events, tuple):
                events = list(maybe_events)  # type: ignore[assignment]

        busy_intervals = self._extract_busy_intervals(events, time_min, time_max)
        return list(events), busy_intervals

    def _extract_busy_intervals(
        self,
        events: Sequence[Mapping[str, Any]],
        day_start: datetime,
        day_end: datetime,
    ) -> List[Tuple[datetime, datetime]]:
        blocks: List[Tuple[datetime, datetime]] = []

        for event in events:
            start = self._parse_datetime(event.get("start"))
            end = self._parse_datetime(event.get("end"))

            if start is None:
                continue
            if end is None:
                end = start + self._slot_duration

            start = start.astimezone(self._timezone)
            end = end.astimezone(self._timezone)

            if end <= day_start or start >= day_end:
                continue

            clipped_start = max(start, day_start)
            clipped_end = min(end, day_end)

            if clipped_end <= clipped_start:
                continue

            blocks.append((clipped_start, clipped_end))

        if not blocks:
            return []

        blocks.sort(key=lambda item: item[0])

        merged: List[Tuple[datetime, datetime]] = [blocks[0]]
        for current_start, current_end in blocks[1:]:
            last_start, last_end = merged[-1]
            if current_start <= last_end:
                merged[-1] = (last_start, max(last_end, current_end))
            else:
                merged.append((current_start, current_end))

        return merged

    def _generate_slots(
        self,
        day_start: datetime,
        day_end: datetime,
        busy_intervals: Sequence[Tuple[datetime, datetime]],
    ) -> List[Slot]:
        slots: List[Slot] = []
        cursor = day_start

        for busy_start, busy_end in busy_intervals:
            while cursor + self._slot_duration <= busy_start:
                slot = Slot(
                    slot_id=f"slot-{cursor.isoformat()}",
                    start=cursor,
                    end=cursor + self._slot_duration,
                    timezone=self._timezone,
                )
                slots.append(slot)
                cursor += self._slot_duration

            cursor = max(cursor, busy_end)
            if cursor >= day_end:
                break

        while cursor + self._slot_duration <= day_end:
            slot = Slot(
                slot_id=f"slot-{cursor.isoformat()}",
                start=cursor,
                end=cursor + self._slot_duration,
                timezone=self._timezone,
            )
            slots.append(slot)
            cursor += self._slot_duration

        return slots

    def _has_conflict(
        self,
        start: datetime,
        end: datetime,
        busy_intervals: Sequence[Tuple[datetime, datetime]],
    ) -> bool:
        for busy_start, busy_end in busy_intervals:
            if start < busy_end and end > busy_start:
                return True
        return False

    def _extract_structured(self, result: mcp_types.CallToolResult) -> Any:
        structured = result.structuredContent
        if structured is None:
            text = self._extract_text(result.content)
            if text:
                with suppress(json.JSONDecodeError):
                    return json.loads(text)
            return None

        if isinstance(structured, dict) and "result" in structured and len(structured) == 1:
            return structured["result"]
        return structured

    def _extract_text(self, content: Iterable[mcp_types.ContentBlock]) -> str:
        texts: List[str] = []
        for block in content:
            if isinstance(block, mcp_types.TextContent):
                texts.append(block.text)
        return "\n".join(texts).strip()

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        if not value:
            return None

        if isinstance(value, Mapping):
            value = value.get("dateTime") or value.get("date")

        if not isinstance(value, str):
            return None

        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self._timezone)

        return dt.astimezone(self._timezone)

    def _day_boundaries(self, day) -> Tuple[datetime, datetime]:
        day_start = datetime.combine(day, self._workday_start, tzinfo=self._timezone)
        day_end = datetime.combine(day, self._workday_end, tzinfo=self._timezone)

        if day_end <= day_start:
            day_end = day_start + timedelta(days=1)

        return day_start, day_end

    def _parse_time(self, value: str) -> time_cls:
        try:
            parsed = datetime.strptime(value, "%H:%M").time()
        except ValueError as exc:
            raise ValueError(f"Invalid time value '{value}'. Use HH:MM format.") from exc
        return parsed
