#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Pipecat Quickstart Example.

The example runs a simple voice AI bot that you can connect to using your
browser and speak with it. You can also deploy this bot to Pipecat Cloud.

Required AI services:
- Deepgram (Speech-to-Text)
- OpenAI (LLM)
- Cartesia (Text-to-Speech)

Run the bot using::

    uv run bot.py
"""

import os
import re
from datetime import datetime, date as date_cls
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from loguru import logger

print("🚀 Starting Pipecat bot...")
print("⏳ Loading models and imports (20 seconds, first run only)\n")

logger.info("Loading Local Smart Turn Analyzer V3...")
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

logger.info("✅ Local Smart Turn Analyzer V3 loaded")
logger.info("Loading Silero VAD model...")
from pipecat.audio.vad.silero import SileroVADAnalyzer

logger.info("✅ Silero VAD model loaded")

from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame

logger.info("Loading pipeline components...")
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams
from services.appointment_service import AppointmentService

logger.info("✅ All components loaded successfully!")

load_dotenv(override=True)


class AppointmentSessionState:
    """Conversation-scoped cache for the most recent slot list."""

    def __init__(self, timezone: str):
        self.latest_slots: list[Dict[str, Any]] = []
        self.last_requested_date: Optional[str] = None
        self._timezone = ZoneInfo(timezone)
        self._time_range_pattern = re.compile(
            r"(?P<start>\d{1,2}:\d{2}\s*(?:AM|PM))\s*-\s*(?P<end>\d{1,2}:\d{2}\s*(?:AM|PM))",
            flags=re.IGNORECASE,
        )

    def record_slots(self, result: Any, *, request_date: str) -> list[Dict[str, Any]]:
        """Parse the MCP response into structured slot data."""
        self.last_requested_date = request_date
        slot_entries: list[Dict[str, Any]] = []

        slot_labels: list[str] = []

        if isinstance(result, Mapping):
            structured_slots = result.get("slots")
            if isinstance(structured_slots, list) and structured_slots:
                for idx, entry in enumerate(structured_slots):
                    if not isinstance(entry, Mapping):
                        continue
                    slot_entries.append(
                        {
                            "label": entry.get("label") or f"Slot {idx + 1}",
                            "index": idx,
                            "id": entry.get("id"),
                            "start_time": entry.get("start_time"),
                            "end_time": entry.get("end_time"),
                            "timezone": entry.get("timezone") or self._timezone.key,
                        }
                    )
                self.latest_slots = slot_entries
                return slot_entries

            results_list = result.get("results")
            if isinstance(results_list, list):
                for entry in results_list:
                    if isinstance(entry, Mapping):
                        value = entry.get("result")
                        if isinstance(value, str):
                            slot_labels.extend(
                                s.strip() for s in value.split(",") if s and s.strip()
                            )
        elif isinstance(result, str):
            slot_labels.extend(s.strip() for s in result.split(",") if s and s.strip())

        date_str = request_date.split("T")[0]
        base_date: Optional[date_cls]
        try:
            base_date = date_cls.fromisoformat(date_str)
        except ValueError:
            base_date = None

        for idx, label in enumerate(slot_labels):
            slot_info: Dict[str, Any] = {"label": label, "index": idx}
            match = self._time_range_pattern.search(label)
            if base_date and match:
                start_iso = self._combine_to_iso(base_date, match.group("start"))
                end_iso = self._combine_to_iso(base_date, match.group("end"))
                if start_iso and end_iso:
                    slot_info["start_time"] = start_iso
                    slot_info["end_time"] = end_iso
            slot_entries.append(slot_info)

        self.latest_slots = slot_entries
        return slot_entries

    def _combine_to_iso(self, base_date: date_cls, time_label: str) -> Optional[str]:
        """Combine a date and a labelled time into an ISO-8601 string."""
        try:
            time_obj = datetime.strptime(time_label.upper(), "%I:%M %p").time()
        except ValueError:
            return None

        combined = datetime.combine(base_date, time_obj, tzinfo=self._timezone)
        return combined.isoformat()

    def with_slot_context(self, arguments: Mapping[str, Any]) -> Dict[str, Any]:
        """Enrich payloads with slot context derived from the last slot list."""
        payload: Dict[str, Any] = dict(arguments)
        slot_info: Optional[Dict[str, Any]] = None

        slot_index = payload.pop("slot_index", None)
        if slot_index is not None:
            try:
                idx = int(slot_index)
                if 0 <= idx < len(self.latest_slots):
                    slot_info = self.latest_slots[idx]
            except (TypeError, ValueError):
                slot_info = None

        slot_label = payload.get("slot_label")
        if slot_info is None and slot_label:
            slot_info = next(
                (slot for slot in self.latest_slots if slot.get("label") == slot_label),
                None,
            )

        if slot_info:
            payload.setdefault("slot_label", slot_info.get("label"))
            start_time = slot_info.get("start_time")
            end_time = slot_info.get("end_time")
            slot_id = slot_info.get("id")
            if slot_id is not None:
                payload.setdefault("slot_id", slot_id)
            if start_time:
                payload.setdefault("date", start_time)
                payload.setdefault("start_time", start_time)
            if end_time:
                payload.setdefault("end_time", end_time)

        return payload


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info(f"Starting bot")

    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",  # British Reading Lady
    )

    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"))

    appointment_timezone = os.getenv("APPOINTMENT_TIMEZONE", "Asia/Kolkata")
    try:
        default_duration_minutes = int(os.getenv("DEFAULT_EVENT_DURATION_MINUTES", "30"))
    except ValueError:
        default_duration_minutes = 30

    appointment_service = AppointmentService(
        server_url=os.getenv("MCP_SERVER_URL", "http://127.0.0.1:9079"),
        calendar_id=os.getenv("GOOGLE_CALENDAR_ID", "primary"),
        timezone=appointment_timezone,
        default_duration_minutes=default_duration_minutes,
        api_key=os.getenv("MCP_API_KEY"),
        workday_start=os.getenv("APPOINTMENT_DAY_START"),
        workday_end=os.getenv("APPOINTMENT_DAY_END"),
    )
    session_state = AppointmentSessionState(timezone=appointment_timezone)

    custom_prompt = os.getenv("BOT_SYSTEM_PROMPT")
    scheduling_instructions = (
        "You schedule doctor appointments for patients. "
        "Gather the patient's name, preferred date, doctor and any symptoms. "
        "Use the provided tools to list slots, check availability, and book visits. "
        "Whenever you reference a slot from the latest list, include its slot_index so tools can identify it. "
        "Always confirm the slot choice and patient details before booking, and summarise the final appointment."
    )
    if custom_prompt:
        system_prompt = f"{custom_prompt.strip()}\n\n{scheduling_instructions}"
    else:
        system_prompt = scheduling_instructions

    context = OpenAILLMContext(
        [
            {
                "role": "system",
                "content": system_prompt,
            }
        ]
    )

    tools = ToolsSchema(
        [
            FunctionSchema(
                name="get_available_slots",
                description=(
                    "Retrieve upcoming appointment slots for a specific day. "
                    "Always provide the appointment date in YYYY-MM-DD format."
                ),
                properties={
                    "doctor": {
                        "type": "string",
                        "description": "Doctor name or identifier to filter the slot list.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Preferred appointment date in ISO format (YYYY-MM-DD).",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "Timezone to return times in, e.g. 'Asia/Kolkata'.",
                    },
                },
                required=["date"],
            ),
            FunctionSchema(
                name="check_slot_availability",
                description=(
                    "Check whether a specific slot is still free before booking. "
                    "Pass the slot identifier returned from get_available_slots. "
                    "You may also pass slot_index to reference a slot by its list position."
                ),
                properties={
                    "date": {
                        "type": "string",
                        "description": "Start time of the slot in ISO 8601 format (auto-filled when slot_index is provided).",
                    },
                    "slot_id": {
                        "type": "string",
                        "description": "Unique identifier for the slot.",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time of the slot in ISO 8601 format, if available.",
                    },
                    "doctor": {
                        "type": "string",
                        "description": "Doctor assigned to the slot.",
                    },
                    "slot_index": {
                        "type": "integer",
                        "description": "0-based index referencing the most recently listed slot.",
                    },
                },
                required=[],
            ),
            FunctionSchema(
                name="book_slot",
                description=(
                    "Book an appointment for the patient. "
                    "Confirm details with the patient before calling. "
                    "Either slot_id or slot_index must be supplied to identify the slot."
                ),
                properties={
                    "date": {
                        "type": "string",
                        "description": "Start time of the slot in ISO 8601 format (auto-filled when slot_index is provided).",
                    },
                    "slot_label": {
                        "type": "string",
                        "description": "Human readable slot label to reference the time range.",
                    },
                    "slot_id": {
                        "type": "string",
                        "description": "Unique identifier for the slot to book.",
                    },
                    "slot_index": {
                        "type": "integer",
                        "description": "0-based index referencing the slot list retrieved earlier.",
                    },
                    "patient_name": {
                        "type": "string",
                        "description": "Full name of the patient.",
                    },
                    "patient_phone": {
                        "type": "string",
                        "description": "Primary phone number for the patient.",
                    },
                    "patient_email": {
                        "type": "string",
                        "description": "Patient email address, if provided.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Additional notes or reason for the visit.",
                    },
                },
                required=["patient_name", "patient_phone"],
            ),
        ]
    )
    context.set_tools(tools)
    context.set_tool_choice("auto")

    context_aggregator = llm.create_context_aggregator(context)

    async def _handle_get_slots(params: FunctionCallParams):
        filters = dict(params.arguments)
        request_date = filters.get("date")
        if not request_date:
            await params.result_callback(
                {
                    "success": False,
                    "error": "Missing required 'date' parameter (YYYY-MM-DD).",
                }
            )
            return

        result = await appointment_service.fetch_slots(filters)
        slots = session_state.record_slots(result, request_date=request_date)

        if not result.get("success"):
            await params.result_callback(
                {
                    "success": False,
                    "error": result.get("error", "Unable to fetch slots."),
                    "slots": slots,
                    "raw": result,
                }
            )
            return

        if slots:
            slot_labels = ", ".join(slot.get("label", "unknown") for slot in slots)
            message = f"Available slots on {request_date}: {slot_labels}"
        else:
            message = f"No free slots found on {request_date}."

        await params.result_callback(
            {
                "success": True,
                "slots": slots,
                "message": message,
                "raw": result,
            }
        )

    async def _handle_check_availability(params: FunctionCallParams):
        payload = session_state.with_slot_context(params.arguments)
        if "date" not in payload:
            await params.result_callback(
                {
                    "success": False,
                    "error": "No slot selected. Provide slot_index from the last slot list.",
                }
            )
            return

        payload.pop("slot_label", None)

        result = await appointment_service.check_availability(payload)
        if not result.get("success"):
            await params.result_callback(
                {
                    "success": False,
                    "error": result.get("error", "Unable to confirm availability."),
                    "raw": result,
                }
            )
            return

        available = result.get("available")
        message = result.get("message")
        if available is None:
            await params.result_callback(
                {
                    "success": False,
                    "error": message or "No availability status returned.",
                    "raw": result,
                }
            )
            return

        if not message:
            message = "Slot is available." if available else "Slot is no longer available."

        await params.result_callback(
            {
                "success": True,
                "available": available,
                "message": message,
                "raw": result,
            }
        )

    async def _handle_book_slot(params: FunctionCallParams):
        payload = session_state.with_slot_context(params.arguments)
        patient_name = payload.get("patient_name")
        patient_phone = payload.get("patient_phone")

        if not patient_name or not patient_phone:
            await params.result_callback(
                {
                    "success": False,
                    "error": "Patient name and phone are required before booking.",
                }
            )
            return

        if "date" not in payload:
            await params.result_callback(
                {
                    "success": False,
                    "error": "No slot selected. Provide slot_index from the latest slot list.",
                }
            )
            return

        payload.pop("slot_label", None)
        result = await appointment_service.book_slot(payload)
        if not result.get("success"):
            await params.result_callback(
                {
                    "success": False,
                    "error": result.get("error", "Unable to book the appointment."),
                    "raw": result,
                }
            )
            return

        message = result.get("message") or "Appointment booked."
        status_value = result.get("status") or "booked"

        await params.result_callback(
            {
                "success": True,
                "status": status_value or "unknown",
                "message": message,
                "raw": result,
            }
        )

    llm.register_function("get_available_slots", _handle_get_slots, cancel_on_interruption=False)
    llm.register_function(
        "check_slot_availability", _handle_check_availability, cancel_on_interruption=False
    )
    llm.register_function("book_slot", _handle_book_slot, cancel_on_interruption=False)

    greeting_message = {"role": "system", "content": "Say hello and briefly introduce yourself."}

    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    pipeline = Pipeline(
        [
            transport.input(),  # Transport user input
            rtvi,  # RTVI processor
            stt,
            context_aggregator.user(),  # User responses
            llm,  # LLM
            tts,  # TTS
            transport.output(),  # Transport bot output
            context_aggregator.assistant(),  # Assistant spoken responses
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[RTVIObserver(rtvi)],
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client connected")
        context.set_messages([{"role": "system", "content": system_prompt}])
        context.add_message(greeting_message)
        session_state.record_slots([])
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected")
        await appointment_service.aclose()
        await task.cancel()

    @task.event_handler("on_pipeline_finished")
    async def on_pipeline_finished(_task, *_):
        await appointment_service.aclose()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point for the bot starter."""

    transport_params = {
        "daily": lambda: DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            turn_analyzer=LocalSmartTurnAnalyzerV3(),
        ),
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            turn_analyzer=LocalSmartTurnAnalyzerV3(),
        ),
    }

    transport = await create_transport(runner_args, transport_params)

    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
