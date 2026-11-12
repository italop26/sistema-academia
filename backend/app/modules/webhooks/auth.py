import hashlib
import hmac
import json
import re
import time

from fastapi import Request
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import ApplicationError
from app.modules.payments.providers import get_pix_provider
from app.modules.webhooks.schemas import SimulatedEvent

MAX_BODY_BYTES = 16_384
SIGNATURE_WINDOW_SECONDS = 300


def reject_json_constant(_value):
    raise ValueError("Constante JSON inválida")


def unique_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Chave JSON duplicada")
        result[key] = value
    return result


async def authenticated_test_event(request: Request) -> SimulatedEvent:
    get_pix_provider()
    secret = get_settings().pix_webhook_test_secret
    if secret is None:
        raise ApplicationError("pix_webhook_disabled", "Webhook de teste desativado.", 404)
    timestamp = request.headers.get("X-Pix-Test-Timestamp", "")
    signature = request.headers.get("X-Pix-Test-Signature", "")
    if (
        not re.fullmatch(r"[0-9]{10}", timestamp)
        or not re.fullmatch(r"sha256=[0-9a-f]{64}", signature)
        or abs(time.time() - int(timestamp)) > SIGNATURE_WINDOW_SECONDS
    ):
        raise ApplicationError("invalid_webhook_signature", "Autenticação de teste inválida.", 401)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise ApplicationError("webhook_too_large", "Evento de teste excede o limite.", 413)
    expected = (
        "sha256="
        + hmac.new(
            secret.get_secret_value().encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, signature):
        raise ApplicationError("invalid_webhook_signature", "Autenticação de teste inválida.", 401)
    try:
        decoded = json.loads(
            body, object_pairs_hook=unique_json_keys, parse_constant=reject_json_constant
        )
        return SimulatedEvent.model_validate(decoded)
    except (ValueError, ValidationError, RecursionError):
        raise ApplicationError(
            "invalid_webhook_payload", "Evento de teste inválido.", 422
        ) from None
