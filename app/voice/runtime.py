import asyncio
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from app.voice.bot import EmergencyCallVoiceBot, PipecatVoiceBot, prewarm_pipecat_imports
from app.voice.config import VoiceSettings
from app.voice.run_system import prewarm_usecase_imports


class VoiceRuntimeManager:
    """Owns Pipecat voice session lifecycle for browser clients."""

    def __init__(self, settings: VoiceSettings):
        self._settings = settings
        self._active_connections = 0
        self._active_call_connections = 0
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
            "voice_runtime": "pipecat",
            "stt_provider": "deepgram",
            "stt_model": self._settings.stt_model,
            "stt_language": self._settings.stt_language,
            "tts_provider": "deepgram",
            "tts_model": self._settings.tts_model,
            "tts_voice": self._settings.tts_voice,
            "tts_fallback_voice": self._settings.tts_fallback_voice,
            "think_provider": "deterministic",
            "think_model": "rule_based_incident_flow",
            "active_voice_connections": self._active_connections,
            "active_call_connections": self._active_call_connections,
            "warmup_state": self.warmup_state,
            "warmup_error": self._warmup_error,
        }

    async def prewarm(self) -> None:
        if self._warmup_finished_at is not None:
            return
        if self._warmup_started_at is not None and self._warmup_finished_at is None:
            return

        self._warmup_started_at = time.monotonic()
        self._warmup_error = None
        try:
            await asyncio.to_thread(self._prewarm_sync)
            logger.info("Pipecat voice runtime prewarm completed")
        except Exception as exc:
            self._warmup_error = str(exc)
            logger.warning(f"Pipecat voice runtime prewarm failed: {exc}")
        finally:
            self._warmup_finished_at = time.monotonic()

    async def shutdown(self) -> None:
        self._active_connections = 0
        self._active_call_connections = 0

    async def handle_browser_socket(self, websocket: WebSocket) -> None:
        await websocket.accept()

        if not self._settings.configured:
            await websocket.send_json(
                {
                    "type": "Error",
                    "description": (
                        "Voice mode is not configured. Missing environment variables: "
                        + ", ".join(self._settings.missing_required_env_vars)
                    ),
                }
            )
            await websocket.close(code=1011)
            return

        self._active_connections += 1
        try:
            bot = PipecatVoiceBot(self._settings)
            await bot.run(websocket)
        except WebSocketDisconnect:
            logger.info("Browser websocket disconnected")
        except Exception as exc:
            logger.exception(f"Pipecat voice session failed: {exc}")
            try:
                await websocket.send_json({"type": "Error", "description": str(exc)})
            except Exception:
                pass
        finally:
            self._active_connections = max(0, self._active_connections - 1)
            try:
                await websocket.close()
            except Exception:
                pass

    async def handle_call_socket(self, websocket: WebSocket) -> None:
        await websocket.accept()

        if not self._settings.configured:
            await websocket.send_json(
                {
                    "type": "Error",
                    "description": (
                        "Voice mode is not configured. Missing environment variables: "
                        + ", ".join(self._settings.missing_required_env_vars)
                    ),
                }
            )
            await websocket.close(code=1011)
            return

        self._active_call_connections += 1
        try:
            bot = EmergencyCallVoiceBot(self._settings)
            await bot.run(websocket)
        except WebSocketDisconnect:
            logger.info("Call websocket disconnected")
        except Exception as exc:
            logger.exception(f"Emergency call voice session failed: {exc}")
            try:
                await websocket.send_json({"type": "Error", "description": str(exc)})
            except Exception:
                pass
        finally:
            self._active_call_connections = max(0, self._active_call_connections - 1)
            try:
                await websocket.close()
            except Exception:
                pass

    def _prewarm_sync(self) -> None:
        prewarm_pipecat_imports()
        prewarm_usecase_imports()
