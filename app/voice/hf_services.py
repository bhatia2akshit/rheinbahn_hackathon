import asyncio
import io
import tempfile
import wave
from pathlib import Path
from typing import AsyncGenerator

from huggingface_hub import InferenceClient
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame, TranscriptionFrame
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601
from pipecat.utils.tracing.service_decorators import traced_stt, traced_tts


def _pcm16_to_wav_bytes(pcm_audio: bytes, sample_rate: int) -> bytes:
    """Wrap mono PCM16 bytes into a WAV byte payload."""
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit PCM
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_audio)
    return wav_buffer.getvalue()


def _decode_audio_to_pcm16(audio_bytes: bytes, sample_rate: int) -> bytes:
    """Decode encoded audio bytes (wav/flac/mp3) to mono PCM16 bytes."""
    import av
    import numpy as np

    input_buffer = io.BytesIO(audio_bytes)
    output_chunks: list[bytes] = []
    with av.open(input_buffer, mode="r") as container:
        stream = container.streams.audio[0]
        resampler = av.audio.resampler.AudioResampler(
            format="s16",
            layout="mono",
            rate=sample_rate,
        )
        for decoded in container.decode(stream):
            for converted in resampler.resample(decoded):
                array = converted.to_ndarray()
                if array.ndim == 2:
                    mono = array[0]
                else:
                    mono = array
                pcm16 = mono.astype(np.int16, copy=False)
                output_chunks.append(pcm16.tobytes())
        for converted in resampler.resample(None):
            array = converted.to_ndarray()
            if array.ndim == 2:
                mono = array[0]
            else:
                mono = array
            pcm16 = mono.astype(np.int16, copy=False)
            output_chunks.append(pcm16.tobytes())
    return b"".join(output_chunks)


class HFInferenceSTTService(SegmentedSTTService):
    """Segmented STT via Hugging Face Inference API."""

    Settings = STTSettings
    _settings: Settings

    def __init__(
        self,
        *,
        hf_token: str,
        provider: str,
        model: str,
        sample_rate: int = 16000,
        extra_body: dict | None = None,
        settings: Settings | None = None,
        **kwargs,
    ):
        default_settings = self.Settings(model=model)
        if settings is not None:
            default_settings.apply_update(settings)
        super().__init__(sample_rate=sample_rate, settings=default_settings, **kwargs)
        self._client = InferenceClient(provider=provider, api_key=hf_token)
        self._model = model
        self._extra_body = extra_body or {}

    @traced_stt
    async def _handle_transcription(self, transcript: str, is_final: bool):
        pass

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        await self.start_processing_metrics()
        temp_wav_path: str | None = None
        try:
            # Hugging Face binary ASR requires a supported audio MIME type.
            # Pipecat segments are raw PCM16, so we wrap and send as a real .wav file.
            wav_audio = _pcm16_to_wav_bytes(audio, self.sample_rate)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
                temp_audio.write(wav_audio)
                temp_wav_path = temp_audio.name

            response = await asyncio.to_thread(
                self._client.automatic_speech_recognition,
                temp_wav_path,
                model=self._model,
                extra_body=self._extra_body,
            )
            transcript = ""
            if hasattr(response, "text"):
                transcript = (response.text or "").strip()
            elif isinstance(response, str):
                transcript = response.strip()
            elif isinstance(response, dict):
                transcript = str(response.get("text", "")).strip()

            await self.stop_processing_metrics()

            if transcript:
                await self._handle_transcription(transcript, True)
                yield TranscriptionFrame(
                    transcript,
                    self._user_id,
                    time_now_iso8601(),
                    self._settings.language if hasattr(self._settings, "language") else None,
                )
            else:
                yield ErrorFrame("HF STT returned empty transcription")
        except Exception as exc:
            await self.stop_processing_metrics()
            logger.exception(f"HF STT failed: {exc}")
            yield ErrorFrame(f"HF STT failed: {exc}")
        finally:
            if temp_wav_path:
                try:
                    Path(temp_wav_path).unlink(missing_ok=True)
                except Exception:
                    logger.debug(f"Could not remove temp STT file: {temp_wav_path}")


class HFInferenceTTSService(TTSService):
    """TTS via Hugging Face Inference API text_to_speech task."""

    Settings = TTSSettings
    _settings: Settings

    def __init__(
        self,
        *,
        hf_token: str,
        provider: str,
        model: str,
        sample_rate: int = 24000,
        extra_body: dict | None = None,
        settings: Settings | None = None,
        **kwargs,
    ):
        default_settings = self.Settings(model=model)
        if settings is not None:
            default_settings.apply_update(settings)
        super().__init__(
            sample_rate=sample_rate,
            push_start_frame=True,
            push_stop_frames=True,
            settings=default_settings,
            **kwargs,
        )
        self._client = InferenceClient(provider=provider, api_key=hf_token)
        self._model = model
        self._extra_body = extra_body or {}

    def can_generate_metrics(self) -> bool:
        return True

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        if not text.strip():
            return
        try:
            audio_bytes = await asyncio.to_thread(
                self._client.text_to_speech,
                text,
                model=self._model,
                extra_body=self._extra_body,
            )
            pcm_audio = await asyncio.to_thread(
                _decode_audio_to_pcm16,
                audio_bytes,
                self.sample_rate,
            )
            if not pcm_audio:
                yield ErrorFrame("HF TTS returned no audio")
                return
            await self.start_tts_usage_metrics(text)
            chunk_size = self.chunk_size
            for i in range(0, len(pcm_audio), chunk_size):
                chunk = pcm_audio[i : i + chunk_size]
                if chunk:
                    await self.stop_ttfb_metrics()
                    yield TTSAudioRawFrame(
                        chunk,
                        self.sample_rate,
                        1,
                        context_id=context_id,
                    )
        except Exception as exc:
            logger.exception(f"HF TTS failed: {exc}")
            yield ErrorFrame(f"HF TTS failed: {exc}")
