import asyncio
import time
import uuid
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.database import SessionLocal
from app.voice.config import VoiceSettings


class VoiceRuntimeManager:
    """Owns WebRTC signaling handlers and per-connection Pipecat pipelines."""

    def __init__(self, settings: VoiceSettings):
        self._settings = settings
        self._request_handler = None
        self._pipeline_tasks: dict[str, asyncio.Task[None]] = {}
        self._active_sessions: dict[str, dict[str, Any]] = {}
        self._warmup_started_at: float | None = None
        self._warmup_finished_at: float | None = None
        self._warmup_error: str | None = None
        if self._settings.config_warning:
            logger.warning(f"Voice config warning: {self._settings.config_warning}")

    @property
    def configured(self) -> bool:
        return self._settings.configured

    @property
    def warmup_state(self) -> str:
        if self._warmup_started_at is None:
            return "idle"
        if self._warmup_finished_at is None:
            return "warming"
        if self._warmup_error:
            return "error"
        return "ready"

    def status(self) -> dict[str, Any]:
        return {
            "configured": self._settings.configured,
            "missing_env_vars": self._settings.missing_required_env_vars,
            "config_warning": self._settings.config_warning,
            "default_postal_code": self._settings.default_postal_code,
            "stt_provider": "deepgram",
            "stt_model": self._settings.stt_model,
            "stt_language": self._settings.stt_language,
            "tts_provider": "deepgram",
            "tts_model": self._settings.tts_model,
            "tts_voice": self._settings.tts_voice,
            "llm_polisher_enabled": bool(self._settings.hf_token),
            "llm_model": self._settings.llm_model,
            "active_voice_connections": len(self._pipeline_tasks),
            "warmup_state": self.warmup_state,
            "warmup_error": self._warmup_error,
        }

    async def prewarm(self) -> None:
        """Warm voice runtime imports and request handler at app startup."""
        if self._warmup_finished_at is not None:
            return
        if self._warmup_started_at is not None and self._warmup_finished_at is None:
            return

        self._warmup_started_at = time.monotonic()
        self._warmup_error = None
        try:
            await asyncio.to_thread(self._prewarm_sync)
            logger.info("Voice runtime prewarm completed")
        except Exception as exc:
            self._warmup_error = str(exc)
            logger.warning(f"Voice runtime prewarm failed: {exc}")
        finally:
            self._warmup_finished_at = time.monotonic()

    def create_session(self, body: dict[str, Any], enable_default_ice_servers: bool) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        self._active_sessions[session_id] = body

        result: dict[str, Any] = {"sessionId": session_id}
        if enable_default_ice_servers:
            result["iceConfig"] = {
                "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}],
            }
        return result

    def get_session_body(self, session_id: str) -> dict[str, Any] | None:
        return self._active_sessions.get(session_id)

    async def handle_offer_payload(
        self,
        payload: dict[str, Any],
        fallback_request_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequest
        except ModuleNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Pipecat WebRTC dependencies are missing. Install requirements and use the venv."
                ),
            ) from exc

        if not self._settings.configured:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Voice mode is not configured. Missing environment variables: "
                    + ", ".join(self._settings.missing_required_env_vars)
                ),
            )

        if fallback_request_data:
            if payload.get("requestData") is None and payload.get("request_data") is None:
                payload["requestData"] = fallback_request_data

        try:
            offer_request = SmallWebRTCRequest.from_dict(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid WebRTC offer payload: {exc}") from exc

        request_handler = self._ensure_request_handler()
        answer = await request_handler.handle_web_request(
            request=offer_request,
            webrtc_connection_callback=self._start_connection_pipeline,
        )
        if not answer:
            raise HTTPException(status_code=500, detail="Unable to generate WebRTC answer")
        return answer

    async def handle_patch_payload(self, payload: dict[str, Any]) -> dict[str, str]:
        try:
            from pipecat.transports.smallwebrtc.request_handler import (
                IceCandidate,
                SmallWebRTCPatchRequest,
            )
        except ModuleNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Pipecat WebRTC dependencies are missing. Install requirements and use the venv."
                ),
            ) from exc

        pc_id = payload.get("pc_id") or payload.get("pcId")
        if not pc_id:
            raise HTTPException(status_code=400, detail="Missing pc_id in ICE patch payload")

        candidates: list[IceCandidate] = []
        for raw_candidate in payload.get("candidates", []):
            sdp_mid = raw_candidate.get("sdp_mid") or raw_candidate.get("sdpMid")
            sdp_mline_index = raw_candidate.get("sdp_mline_index") or raw_candidate.get(
                "sdpMLineIndex"
            )
            if sdp_mid is None or sdp_mline_index is None:
                raise HTTPException(
                    status_code=400,
                    detail="Each ICE candidate must include sdpMid/sdpMLineIndex",
                )
            candidates.append(
                IceCandidate(
                    candidate=raw_candidate["candidate"],
                    sdp_mid=sdp_mid,
                    sdp_mline_index=int(sdp_mline_index),
                )
            )

        patch_request = SmallWebRTCPatchRequest(pc_id=pc_id, candidates=candidates)
        request_handler = self._ensure_request_handler()
        await request_handler.handle_patch_request(patch_request)
        return {"status": "success"}

    async def shutdown(self) -> None:
        tasks = list(self._pipeline_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._request_handler is not None:
            await self._request_handler.close()
        self._pipeline_tasks.clear()
        self._active_sessions.clear()

    async def _start_connection_pipeline(self, connection) -> None:
        pc_id = connection.pc_id
        if pc_id in self._pipeline_tasks:
            existing = self._pipeline_tasks[pc_id]
            if not existing.done():
                existing.cancel()

        task = asyncio.create_task(
            self._run_connection_pipeline(connection),
            name=f"voice-pipeline-{pc_id}",
        )
        self._pipeline_tasks[pc_id] = task

        def _cleanup(done_task: asyncio.Task[None]) -> None:
            self._pipeline_tasks.pop(pc_id, None)
            try:
                done_task.result()
            except asyncio.CancelledError:
                logger.debug(f"Voice pipeline {pc_id} cancelled")
            except Exception as exc:
                logger.exception(f"Voice pipeline {pc_id} crashed: {exc}")

        task.add_done_callback(_cleanup)

    async def _run_connection_pipeline(self, connection) -> None:
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.runner import PipelineRunner
        from pipecat.pipeline.task import PipelineParams, PipelineTask
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        from pipecat.services.deepgram.stt import DeepgramSTTService
        from pipecat.services.deepgram.tts import DeepgramTTSService
        from pipecat.transports.base_transport import TransportParams
        from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
        from app.voice.processor import IncidentSpeechProcessor

        transport = SmallWebRTCTransport(
            webrtc_connection=connection,
            params=TransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_channels=1,
                audio_out_channels=1,
                audio_in_sample_rate=16000,
                audio_out_sample_rate=self._settings.tts_sample_rate,
                vad_enabled=True,
                vad_analyzer=SileroVADAnalyzer(),
            ),
        )

        stt_settings = DeepgramSTTService.Settings(
            model=self._settings.stt_model,
            language=self._settings.stt_language,
            interim_results=False,
            punctuate=True,
            smart_format=True,
        )
        stt = DeepgramSTTService(
            api_key=self._settings.deepgram_api_key or "",
            encoding="linear16",
            channels=1,
            sample_rate=16000,
            settings=stt_settings,
        )

        tts_settings = DeepgramTTSService.Settings(
            model=self._settings.tts_model,
            voice=self._settings.tts_voice,
            language=self._settings.stt_language,
        )
        tts = DeepgramTTSService(
            api_key=self._settings.deepgram_api_key or "",
            sample_rate=self._settings.tts_sample_rate,
            encoding=self._settings.tts_encoding,
            settings=tts_settings,
        )

        script_refiner = None
        if self._settings.hf_token:
            try:
                from app.voice.hf_llm import HFRouterLLMPolisher

                llm_polisher = HFRouterLLMPolisher(
                    hf_token=self._settings.hf_token,
                    model=self._settings.llm_model,
                    temperature=self._settings.llm_temperature,
                    max_tokens=self._settings.llm_max_tokens,
                )
                script_refiner = llm_polisher.polish_script
            except Exception as exc:
                logger.warning(f"HF LLM polisher init failed. Continuing without polish: {exc}")

        incident_processor = IncidentSpeechProcessor(
            session_id=connection.pc_id,
            db_session_factory=SessionLocal,
            default_postal_code=self._settings.default_postal_code,
            script_refiner=script_refiner,
        )
        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                incident_processor,
                tts,
                transport.output(),
            ]
        )
        pipeline_task = PipelineTask(
            pipeline,
            params=PipelineParams(
                allow_interruptions=True,
            ),
        )
        runner = PipelineRunner(handle_sigint=False, handle_sigterm=False)

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(_transport, webrtc_connection) -> None:
            logger.info(f"WebRTC client disconnected for pc_id={webrtc_connection.pc_id}")
            await runner.cancel()

        logger.info(f"Starting voice pipeline for pc_id={connection.pc_id}")
        await runner.run(pipeline_task)
        logger.info(f"Voice pipeline finished for pc_id={connection.pc_id}")

    def _prewarm_sync(self) -> None:
        """Synchronous warm-up: import heavy modules and init request handler."""
        # Pipecat transport/pipeline imports
        from pipecat.audio.vad.silero import SileroVADAnalyzer  # noqa: F401
        from pipecat.pipeline.pipeline import Pipeline  # noqa: F401
        from pipecat.pipeline.runner import PipelineRunner  # noqa: F401
        from pipecat.pipeline.task import PipelineParams, PipelineTask  # noqa: F401
        from pipecat.services.deepgram.stt import DeepgramSTTService  # noqa: F401
        from pipecat.services.deepgram.tts import DeepgramTTSService  # noqa: F401
        from pipecat.transports.base_transport import TransportParams  # noqa: F401
        from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport  # noqa: F401

        # Local voice imports
        from app.voice.processor import IncidentSpeechProcessor  # noqa: F401
        if self._settings.hf_token:
            from app.voice.hf_llm import HFRouterLLMPolisher  # noqa: F401

        # Ensure request handler is ready for first offer.
        self._ensure_request_handler()

    def _ensure_request_handler(self):
        if self._request_handler is None:
            try:
                from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequestHandler
            except ModuleNotFoundError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Pipecat WebRTC dependencies are not installed in this environment. "
                        "Install from requirements.txt and run inside the project virtualenv."
                    ),
                ) from exc

            self._request_handler = SmallWebRTCRequestHandler()
        return self._request_handler
