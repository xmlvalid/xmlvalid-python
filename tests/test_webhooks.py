from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from xmlvalid import Event, SignatureVerificationError, webhooks

from .conftest import validation

SECRET = "whsec_test"
NOW = 1_800_000_000


def sign(body: bytes, timestamp: int = NOW, secret: str = SECRET) -> str:
    return f"t={timestamp},v1=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def body(event_type: str = "validation.completed") -> bytes:
    data = validation() if event_type == "validation.completed" else {"message": "A test event from xmlvalid.com."}
    return json.dumps(
        {"id": "evt_1", "type": event_type, "created_at": "2026-10-18T10:00:00+00:00", "data": data}
    ).encode()


def test_a_signed_event_is_read() -> None:
    event = webhooks.verify(body(), sign(body()), SECRET, now=NOW)

    assert (event.id, event.type) == ("evt_1", Event.VALIDATION_COMPLETED)
    assert event.validation is not None and event.validation.is_valid
    assert event.created_at is not None and event.created_at.year == 2026


def test_a_ping_has_no_validation_and_a_str_body_works() -> None:
    raw = body("ping")

    event = webhooks.verify(raw.decode(), sign(raw), SECRET, now=NOW)

    assert event.type == Event.PING and event.validation is None


def test_any_v1_signature_may_match() -> None:
    raw = body()
    signature = f"t={NOW},v1={'0' * 64}," + sign(raw).split(",")[1]

    assert webhooks.verify(raw, signature, SECRET, now=NOW).id == "evt_1"


@pytest.mark.parametrize(
    ("signature", "message"),
    [
        (None, "missing or malformed"),
        ("v1=abc", "missing or malformed"),
        (sign(body(), NOW - 301), "too old"),
        (sign(body(), secret="whsec_other"), "does not match"),
        (sign(b"not json"), "not JSON"),
        (sign(b"[1]"), "not a JSON object"),
    ],
)
def test_bad_signatures_are_refused(signature: str | None, message: str) -> None:
    raw = b"not json" if signature is not None and signature == sign(b"not json") else body()
    raw = b"[1]" if signature is not None and signature == sign(b"[1]") else raw

    with pytest.raises(SignatureVerificationError, match=message):
        webhooks.verify(raw, signature, SECRET, now=NOW)


def test_the_age_check_can_be_skipped() -> None:
    raw = body()

    assert webhooks.verify(raw, sign(raw, 1), SECRET, tolerance=0).id == "evt_1"
