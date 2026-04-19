from __future__ import annotations

import asyncio
import json
import uuid
from typing import Awaitable, Callable, Protocol

from fastapi import WebSocket
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    InputAudioRawFrame,
    InputTextRawFrame,
    InterimTranscriptionFrame,
    OutputAudioRawFrame,
    OutputTransportReadyFrame,
    OutputTransportMessageFrame,
    StartFrame,
    TTSSpeakFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from app.services.emergency_dispatch import DispatchServiceKey
from app.voice.call_system import EmergencyCallOrchestrator
from app.voice.config import VoiceSettings
from app.voice.run_system import VoiceTurnResult, VoiceUsecaseOrchestrator


class BrowserPcmSerializer(FrameSerializer):
    """Serialize browser PCM websocket traffic to Pipecat audio frames."""

    def __init__(self):
        super().__init__()
        self._input_sample_rate = 16000
        self._input_channels = 1

    async def setup(self, frame: StartFrame):
        self._input_sample_rate = frame.audio_in_sample_rate
        self._input_channels = getattr(frame, "audio_in_channels", 1)

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if self.should_ignore_frame(frame):
            return None
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        if isinstance(frame, OutputTransportMessageFrame):
            return json.dumps(frame.message)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, (bytes, bytearray)):
            return InputAudioRawFrame(
                audio=bytes(data),
                sample_rate=self._input_sample_rate,
                num_channels=self._input_channels,
            )

        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return None

        if payload.get("type") == "InjectUserMessage":
            content = str(payload.get("content", "")).strip()
            if content:
                return InputTextRawFrame(text=content)
        return None


class VoiceFlowProcessor(FrameProcessor):
    """Collect finalized user utterances and generate deterministic bot prompts."""

    def __init__(
        self,
        orchestrator: ConversationOrchestrator,
        turn_pause_secs: float = 1.8,
        stop_speaking_grace_secs: float = 0.45,
    ):
        super().__init__()
        self._orchestrator = orchestrator
        self._prompted = False
        self._completed = False
        self._on_complete: Callable[[], Awaitable[None]] | None = None
        self._turn_pause_secs = turn_pause_secs
        self._stop_speaking_grace_secs = stop_speaking_grace_secs
        self._pending_transcript_parts: list[str] = []
        self._pending_emit_task: asyncio.Task[None] | None = None
        self._user_currently_speaking = False

    def set_on_complete(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._on_complete = callback

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, OutputTransportReadyFrame):
            await self.push_frame(frame, direction)
            if not self._prompted:
                self._prompted = True
                await self._emit_turn(self._orchestrator.start_conversation())
            return

        if isinstance(frame, InterimTranscriptionFrame):
            return

        if isinstance(frame, UserStartedSpeakingFrame):
            self._user_currently_speaking = True
            await self._cancel_pending_emit()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserStoppedSpeakingFrame):
            self._user_currently_speaking = False
            await self.push_frame(frame, direction)
            if self._pending_transcript_parts:
                await self._schedule_pending_emit(delay_secs=self._stop_speaking_grace_secs)
            return

        if isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text:
                self._pending_transcript_parts.append(text)
                if not self._user_currently_speaking:
                    await self._schedule_pending_emit()
            return

        if isinstance(frame, InputTextRawFrame):
            text = frame.text.strip()
            if text:
                await self._flush_pending_transcript()
                await self._emit_turn(self._orchestrator.on_user_text(text))
            return

        await self.push_frame(frame, direction)

    async def _schedule_pending_emit(self, delay_secs: float | None = None) -> None:
        await self._cancel_pending_emit()
        chosen_delay = delay_secs if delay_secs is not None else self._turn_pause_secs
        self._pending_emit_task = asyncio.create_task(
            self._delayed_emit_pending_transcript(chosen_delay)
        )

    async def _delayed_emit_pending_transcript(self, delay_secs: float) -> None:
        try:
            await asyncio.sleep(delay_secs)
            await self._flush_pending_transcript()
        except asyncio.CancelledError:
            return

    async def _cancel_pending_emit(self) -> None:
        if self._pending_emit_task:
            self._pending_emit_task.cancel()
            self._pending_emit_task = None

    async def _flush_pending_transcript(self) -> None:
        if self._pending_emit_task:
            task = self._pending_emit_task
            self._pending_emit_task = None
            if task is not asyncio.current_task():
                task.cancel()

        if not self._pending_transcript_parts:
            return

        merged_text = " ".join(part.strip() for part in self._pending_transcript_parts if part.strip())
        self._pending_transcript_parts.clear()
        if merged_text:
            await self._emit_turn(self._orchestrator.on_user_text(merged_text))

    async def _emit_turn(self, turn: VoiceTurnResult) -> None:
        for reply in turn.replies:
            self._orchestrator.add_assistant_message(reply)
            await self.push_frame(TTSSpeakFrame(reply), FrameDirection.DOWNSTREAM)

        if turn.completed and not self._completed:
            self._completed = True
            if self._on_complete:
                await self._on_complete()


class ConversationOrchestrator(Protocol):
    def start_conversation(self) -> VoiceTurnResult:
        ...

    def add_assistant_message(self, content: str) -> None:
        ...

    def on_user_text(self, content: str) -> VoiceTurnResult:
        ...


class BasePipecatVoiceBot:
    def __init__(self, settings: VoiceSettings):
        self._settings = settings

    async def _run_orchestrator(
        self,
        websocket: WebSocket,
        orchestrator: ConversationOrchestrator,
    ) -> None:
        serializer = BrowserPcmSerializer()

        transport = FastAPIWebsocketTransport(
            websocket,
            FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_in_sample_rate=16000,
                audio_out_enabled=True,
                audio_out_sample_rate=self._settings.tts_sample_rate,
                audio_out_channels=1,
                audio_out_auto_silence=False,
                audio_out_end_silence_secs=0,
                serializer=serializer,
                session_timeout=180,
            ),
        )

        stt = DeepgramSTTService(
            api_key=self._settings.deepgram_api_key or "",
            sample_rate=16000,
            audio_passthrough=False,
            keepalive_timeout=10.0,
            keepalive_interval=5.0,
            settings=DeepgramSTTService.Settings(
                model=self._settings.stt_model,
                language=self._settings.stt_language,
                interim_results=True,
                punctuate=True,
                smart_format=True,
                endpointing=1800,
                utterance_end_ms=1800,
                vad_events=True,
            ),
        )
        tts_voice = self._settings.tts_voice or self._settings.tts_model
        tts = DeepgramTTSService(
            api_key=self._settings.deepgram_api_key or "",
            voice=tts_voice,
            sample_rate=self._settings.tts_sample_rate,
            encoding=self._settings.tts_encoding,
            settings=DeepgramTTSService.Settings(
                voice=tts_voice,
            ),
        )
        flow = VoiceFlowProcessor(
            orchestrator,
            turn_pause_secs=1.8,
            stop_speaking_grace_secs=0.45,
        )

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                flow,
                tts,
                transport.output(),
            ]
        )
        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                audio_in_sample_rate=16000,
                audio_out_sample_rate=self._settings.tts_sample_rate,
            ),
            enable_rtvi=False,
            enable_turn_tracking=False,
        )
        flow.set_on_complete(task.stop_when_done)

        errors: list[str] = []

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(_: FastAPIWebsocketTransport, __: WebSocket):
            await task.stop_when_done()

        @transport.event_handler("on_session_timeout")
        async def on_session_timeout(_: FastAPIWebsocketTransport, __: WebSocket):
            await task.cancel(reason="Voice websocket session timed out.")

        @task.event_handler("on_pipeline_error")
        async def on_pipeline_error(_: PipelineTask, frame: ErrorFrame):
            errors.append(getattr(frame, "error", str(frame)))

        runner = PipelineRunner(handle_sigint=False, handle_sigterm=False)
        await runner.run(task)

        if errors:
            raise RuntimeError(errors[-1])


class PipecatVoiceBot(BasePipecatVoiceBot):
    """Pipecat-based voice bot using Deepgram STT/TTS over a FastAPI websocket."""

    async def run(self, websocket: WebSocket) -> None:
        session_id = str(uuid.uuid4())
        driver_name = websocket.query_params.get("driver_name")
        train_number = websocket.query_params.get("train_number")
        orchestrator = VoiceUsecaseOrchestrator(
            session_id=session_id,
            driver_name=driver_name,
            train_number=train_number,
        )
        await self._run_orchestrator(websocket, orchestrator)


class EmergencyCallVoiceBot(BasePipecatVoiceBot):
    async def run(self, websocket: WebSocket) -> None:
        raw_event_id = websocket.query_params.get("event_id")
        raw_service = websocket.query_params.get("service")
        if raw_event_id is None or raw_service is None:
            raise ValueError("event_id and service query parameters are required for call sessions")

        event_id = int(raw_event_id)
        service = self._normalize_service(raw_service)
        orchestrator = EmergencyCallOrchestrator(event_id=event_id, service=service)
        await self._run_orchestrator(websocket, orchestrator)

    @staticmethod
    def _normalize_service(raw_service: str) -> DispatchServiceKey:
        normalized = raw_service.strip().lower()
        if normalized not in {"police", "rettungs"}:
            raise ValueError(f"Unsupported call service: {raw_service}")
        return normalized  # type: ignore[return-value]


def prewarm_pipecat_imports() -> None:
    _ = (
        BrowserPcmSerializer,
        DeepgramSTTService,
        DeepgramTTSService,
        EmergencyCallVoiceBot,
        FastAPIWebsocketTransport,
        PipecatVoiceBot,
        Pipeline,
        PipelineRunner,
        PipelineTask,
    )
