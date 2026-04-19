from __future__ import annotations

import json
import re
from urllib import error as urlerror
from urllib import request as urlrequest
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from loguru import logger

from app import models
from app.voice.config import load_voice_settings


DispatchServiceKey = Literal["police", "rettungs"]
LocationGroupKey = Literal["between 1 and 2", "between 3 and 4"]

DISPATCH_SERVICE_ORDER: tuple[DispatchServiceKey, ...] = ("police", "rettungs")

_LOCATION_ROUTE_CONFIG: tuple[dict[str, object], ...] = (
    {
        "group": "between 1 and 2",
        "semantic_label": "between station 1 and station 2",
        "numbers": {
            "police": {"label": "Police 1", "display": "+4915168555138"},
            "rettungs": {"label": "Rettung 1", "display": "++4915168555151"},
        },
    },
    {
        "group": "between 3 and 4",
        "semantic_label": "between station 3 and station 4",
        "numbers": {
            "police": {"label": "Police 2", "display": "+4915168555432"},
            "rettungs": {"label": "Rettung 2", "display": "+4915168111123"},
        },
    },
)

_DISPATCH_REQUESTED_PATTERN = re.compile(
    r"Dispatch requested:\s*(?P<targets>[^\n]+)",
    re.IGNORECASE,
)
_LEGACY_DISPATCH_PATTERN = re.compile(
    r"Call emergency and police:\s*(?P<flag>yes|no)",
    re.IGNORECASE,
)
_POLICE_TEXT_PATTERN = re.compile(
    r"\b(polizei|police)\b",
    re.IGNORECASE,
)
_RETTUNG_TEXT_PATTERN = re.compile(
    r"\b(rettung|rettungsdienst|rettungsnummer|ambulanz|notarzt|krankenwagen)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DispatchCall:
    service: DispatchServiceKey
    service_label: str
    route_label: str
    location_group: str
    display_phone_number: str
    dial_phone_number: str
    call_page_path: str

    def to_payload(self) -> dict[str, str]:
        return {
            "service": self.service,
            "service_label": self.service_label,
            "route_label": self.route_label,
            "location_group": self.location_group,
            "display_phone_number": self.display_phone_number,
            "dial_phone_number": self.dial_phone_number,
            "call_page_path": self.call_page_path,
        }


def build_dispatch_calls_for_event(event: models.Event) -> list[dict[str, str]]:
    requested_services = parse_dispatch_targets_from_description(event.description)
    location_group = infer_location_group(event.location, description=event.description)
    if not requested_services or location_group is None:
        return []

    route = _route_config_for_group(location_group)
    if route is None:
        return []

    numbers = route["numbers"]
    event_id = event.event_id
    calls: list[dict[str, str]] = []
    for service in requested_services:
        service_meta = numbers.get(service)
        if not isinstance(service_meta, dict):
            continue
        display_phone_number = str(service_meta["display"])
        calls.append(
            DispatchCall(
                service=service,
                service_label=_service_label(service),
                route_label=str(service_meta["label"]),
                location_group=location_group,
                display_phone_number=display_phone_number,
                dial_phone_number=_normalize_dial_number(display_phone_number),
                call_page_path=_call_page_path(service, event_id),
            ).to_payload()
        )
    return calls


def infer_location_group(location: str | None, *, description: str | None = None) -> str | None:
    if not location:
        return None

    ai_result = _infer_location_group_via_ai(location=location, description=description)
    if ai_result is not None:
        return ai_result
    return None


def parse_dispatch_targets_from_description(description: str | None) -> list[DispatchServiceKey]:
    if not description:
        return []

    primary_description = _event_summary(description)
    inferred_from_summary = infer_dispatch_targets_from_text(primary_description)

    requested_match = _DISPATCH_REQUESTED_PATTERN.search(description)
    if requested_match:
        targets_text = requested_match.group("targets").strip().lower()
        if targets_text in {"none", "no", "nein"}:
            return inferred_from_summary

        return _ordered_services(
            inferred_from_summary + infer_dispatch_targets_from_text(targets_text)
        )

    legacy_match = _LEGACY_DISPATCH_PATTERN.search(description)
    if legacy_match and legacy_match.group("flag").strip().lower() == "yes":
        return inferred_from_summary

    return inferred_from_summary


def build_dispatch_call_script(event: models.Event, service: DispatchServiceKey) -> str:
    description = _event_summary(event.description).rstrip(" .")
    location = event.location or "an unknown location"
    vehicle = event.train_bus_number or "the vehicle"
    driver_name = event.driver_name or "the driver"
    location_group = infer_location_group(event.location, description=event.description)
    route_suffix = f" The driver said they are {location_group}." if location_group else ""

    if service == "police":
        return (
            f"Hello police, this is the Rheinbahn incident assistant calling on behalf of driver "
            f"{driver_name} from {vehicle}. The reported incident is at {location}. "
            f"What happened: {description}.{route_suffix} Please send police support."
        )

    return (
        f"Hello Rettung, this is the Rheinbahn incident assistant calling on behalf of driver "
        f"{driver_name} from {vehicle}. The reported incident is at {location}. "
        f"What happened: {description}.{route_suffix} Please send medical support if required."
    )


def call_page_title(service: DispatchServiceKey) -> str:
    return "Police Call" if service == "police" else "Rettung Call"


def call_accept_prompt(service: DispatchServiceKey) -> str:
    if service == "police":
        return "Answer as police and start with: How can I help?"
    return "Answer as Rettung and start with: How can I help?"


def _service_label(service: DispatchServiceKey) -> str:
    return "Police" if service == "police" else "Rettung"


def infer_dispatch_targets_from_text(text: str | None) -> list[DispatchServiceKey]:
    if not text:
        return []

    found: list[DispatchServiceKey] = []
    if _POLICE_TEXT_PATTERN.search(text):
        found.append("police")
    if _RETTUNG_TEXT_PATTERN.search(text):
        found.append("rettungs")
    return _ordered_services(found)


def _route_config_for_group(group: str) -> dict[str, object] | None:
    for route in _LOCATION_ROUTE_CONFIG:
        if route["group"] == group:
            return route
    return None


def _ordered_services(services: list[DispatchServiceKey]) -> list[DispatchServiceKey]:
    unique = set(services)
    return [service for service in DISPATCH_SERVICE_ORDER if service in unique]


def _event_summary(description: str | None) -> str:
    if not description:
        return "no description was recorded"
    primary = description.split("\n\n", 1)[0].strip()
    return primary or "no description was recorded"


def _normalize_dial_number(raw_number: str) -> str:
    digits = re.sub(r"[^\d]", "", raw_number)
    return f"+{digits}" if digits else raw_number


def _call_page_path(service: DispatchServiceKey, event_id: int) -> str:
    if service == "police":
        return f"/police/{event_id}"
    return f"/rettungs/{event_id}"


@lru_cache(maxsize=256)
def _infer_location_group_via_ai(location: str, description: str | None = None) -> str | None:
    settings = load_voice_settings()
    if not settings.hf_dispatch_model or not settings.hf_dispatch_token:
        return None

    try:
        generated = _call_hf_inference_api(
            model_name=settings.hf_dispatch_model,
            token=settings.hf_dispatch_token,
            prompt=_build_location_classification_prompt(location=location, description=description),
        )
    except Exception as exc:
        logger.warning(f"HF location classification failed: {exc}")
        return None

    best_group = _parse_location_group_response(generated)
    if best_group is None:
        return None

    for route in _LOCATION_ROUTE_CONFIG:
        if route["group"] == best_group:
            return str(route["group"])
    return None


def _build_location_classification_prompt(location: str, description: str | None) -> str:
    summary = _event_summary(description)
    return (
        "Classify the reported tram location into one of two route groups.\n"
        "Valid output groups are exactly: between 1 and 2, between 3 and 4.\n"
        "The driver may say the numbers in digits or words, for example:\n"
        "- 1 and 2\n"
        "- one and 2\n"
        "- between 3 and 4\n"
        "- drei und vier\n"
        "Return JSON only with keys group and confidence.\n"
        f"Driver location statement: {location}\n"
        f"Incident summary: {summary}\n"
    )


def _call_hf_inference_api(*, model_name: str, token: str, prompt: str) -> str:
    payload = json.dumps(
        {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": 64,
                "temperature": 0.0,
                "return_full_text": False,
            },
        }
    ).encode("utf-8")
    url = f"https://api-inference.huggingface.co/models/{model_name}"
    req = urlrequest.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlrequest.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urlerror.HTTPError as exc:
        raise RuntimeError(f"HF inference API error: {exc.code}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"HF inference API unavailable: {exc.reason}") from exc

    data = json.loads(body)
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and "generated_text" in first:
            return str(first["generated_text"])
    if isinstance(data, dict):
        if "generated_text" in data:
            return str(data["generated_text"])
        if "error" in data:
            raise RuntimeError(str(data["error"]))
    return body


def _parse_location_group_response(response_text: str) -> str | None:
    text = response_text.strip()
    if not text:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        group = payload.get("group")
        if group in {route["group"] for route in _LOCATION_ROUTE_CONFIG}:
            return str(group)

    normalized = text.lower()
    if "between 1 and 2" in normalized or "1 and 2" in normalized:
        return "between 1 and 2"
    if "between 3 and 4" in normalized or "3 and 4" in normalized:
        return "between 3 and 4"
    return None
