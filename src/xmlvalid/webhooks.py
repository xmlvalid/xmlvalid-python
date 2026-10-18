"""Checks and reads the webhooks xmlvalid sends (Dashboard → Webhooks)."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time

from .errors import SignatureVerificationError
from .models import Event

__all__ = ["verify"]


def verify(
    payload: bytes | str,
    signature: str | None,
    secret: str,
    *,
    tolerance: int = 300,
    now: int | None = None,
) -> Event:
    """Checks a webhook's ``Xmlvalid-Signature`` header and returns its event.

    The header is ``t=<unix time>,v1=<HMAC-SHA256 of "t.body" keyed with the endpoint's secret>``.
    Pass the raw body as received. ``tolerance`` is how many seconds a signature stays valid,
    against replays (0 to skip that check).

    Raises :class:`~xmlvalid.errors.SignatureVerificationError`.
    """
    body = payload.encode() if isinstance(payload, str) else payload
    timestamp = re.search(r"(?:^|,)\s*t=(\d+)", signature or "")
    hashes = re.findall(r"(?:^|,)\s*v1=([0-9a-f]+)", signature or "")
    if timestamp is None or not hashes:
        raise SignatureVerificationError("The Xmlvalid-Signature header is missing or malformed.")

    sent = int(timestamp.group(1))
    if tolerance > 0 and abs((now if now is not None else int(time.time())) - sent) > tolerance:
        raise SignatureVerificationError("The webhook signature is too old.")

    expected = hmac.new(secret.encode(), f"{sent}.".encode() + body, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in hashes):
        raise SignatureVerificationError(
            "The webhook signature does not match: check the endpoint's secret and pass the raw body."
        )

    try:
        data = json.loads(body)
    except ValueError as e:
        raise SignatureVerificationError("The webhook body is not JSON.") from e
    if not isinstance(data, dict):
        raise SignatureVerificationError("The webhook body is not a JSON object.")

    return Event.from_dict({str(key): value for key, value in data.items()})
