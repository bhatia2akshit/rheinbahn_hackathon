import os
import re
from dataclasses import dataclass


DEFAULT_POSTAL_CODE = "10115"
_PLZ_PATTERN = re.compile(r"^\d{5}$")


def _default_tts_voice(language: str) -> str:
    if language.lower().startswith("de"):
        return "aura-2-julius-de"
    return "aura-2-helena-en"


def _fallback_tts_voice(language: str) -> str:
    if language.lower().startswith("de"):
        return "aura-2-elara-de"
    return "aura-2-helena-en"


def _normalize_ascii_secret(
    raw: str | None,
    env_name: str,
) -> tuple[str | None, str | None]:
    if not raw:
        return None, None
    cleaned = raw.strip().strip('"').strip("'")
    if any(ord(ch) > 127 for ch in cleaned):
        return None, f"{env_name} contains non-ASCII characters. Please paste a clean token."
    return cleaned or None, None


@dataclass(frozen=True)
class VoiceSettings:
    deepgram_api_key: str | None
    config_warning: str | None
    default_postal_code: str
    hf_dispatch_model: str
    hf_dispatch_token: str | None
    stt_model: str
    stt_language: str
    tts_model: str
    tts_voice: str
    tts_fallback_voice: str
    tts_encoding: str
    tts_sample_rate: int
    think_model: str
    think_temperature: float

    @property
    def missing_required_env_vars(self) -> list[str]:
        return [] if self.deepgram_api_key else ["DEEPGRAM_API_KEY"]

    @property
    def configured(self) -> bool:
        return bool(self.deepgram_api_key)


def load_voice_settings() -> VoiceSettings:
    deepgram_api_key, warning = _normalize_ascii_secret(
        os.getenv("DEEPGRAM_API_KEY") or os.getenv("deepgram_api_key"),
        "DEEPGRAM_API_KEY",
    )
    default_postal_code = os.getenv("VOICE_DEFAULT_POSTAL_CODE", DEFAULT_POSTAL_CODE).strip()
    if not _PLZ_PATTERN.fullmatch(default_postal_code):
        default_postal_code = DEFAULT_POSTAL_CODE
    stt_language = os.getenv("DEEPGRAM_STT_LANGUAGE", "de")
    hf_dispatch_token, _ = _normalize_ascii_secret(
        os.getenv("HF_DISPATCH_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN"),
        "HF_DISPATCH_TOKEN",
    )
    default_tts_voice = _default_tts_voice(stt_language)
    fallback_tts_voice = _fallback_tts_voice(stt_language)

    return VoiceSettings(
        deepgram_api_key=deepgram_api_key,
        config_warning=warning,
        default_postal_code=default_postal_code,
        hf_dispatch_model=os.getenv(
            "HF_DISPATCH_MODEL",
            "Qwen/Qwen2.5-7B-Instruct",
        ),
        hf_dispatch_token=hf_dispatch_token,
        stt_model=os.getenv("DEEPGRAM_STT_MODEL", "nova-3"),
        stt_language=stt_language,
        tts_model=os.getenv("DEEPGRAM_TTS_MODEL", default_tts_voice),
        tts_voice=os.getenv(
            "DEEPGRAM_TTS_VOICE",
            os.getenv("DEEPGRAM_TTS_MODEL", default_tts_voice),
        ),
        tts_fallback_voice=os.getenv("DEEPGRAM_TTS_FALLBACK_VOICE", fallback_tts_voice),
        tts_encoding=os.getenv("DEEPGRAM_TTS_ENCODING", "linear16"),
        tts_sample_rate=int(os.getenv("DEEPGRAM_TTS_SAMPLE_RATE", "24000")),
        think_model=os.getenv("DEEPGRAM_THINK_MODEL", "gpt-4o-mini"),
        think_temperature=float(os.getenv("DEEPGRAM_THINK_TEMPERATURE", "0.2")),
    )
