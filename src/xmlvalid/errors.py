"""Every exception the client raises extends :class:`XmlvalidError`."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Validation

__all__ = [
    "ApiError",
    "AuthenticationError",
    "DocumentTooLargeError",
    "InvalidRequestError",
    "NotFinishedError",
    "NotFoundError",
    "PlanLimitError",
    "QuotaExceededError",
    "RateLimitedError",
    "RulesVersionMismatchError",
    "ServerError",
    "SignatureVerificationError",
    "TransportError",
    "ValidationTimeoutError",
    "XmlvalidError",
]


class XmlvalidError(Exception):
    """Anything that went wrong talking to xmlvalid."""


class ApiError(XmlvalidError):
    """The API refused the request."""

    def __init__(
        self,
        message: str,
        status_code: int,
        error_code: str,
        fields: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        """The HTTP status."""
        self.error_code = error_code
        """The API's code: unauthenticated, invalid_request, quota_exceeded, …"""
        self.fields = fields or {}
        """For invalid_request: the problems per field."""


class AuthenticationError(ApiError):
    """401: no key, or a revoked one."""


class PlanLimitError(ApiError):
    """403: not in your plan."""


class NotFoundError(ApiError):
    """404: no such validation, or it expired (24 hours)."""


class NotFinishedError(ApiError):
    """409: the report of a validation still running."""


class RulesVersionMismatchError(ApiError):
    """409: a rule set pinned with ``rules_version`` runs another release now. Nothing ran and nothing counted."""

    rule_set: str = ""
    """The rule set's key: peppol-bis-3-ubl."""
    pinned: str = ""
    """The release pinned."""
    current: str = ""
    """The release that runs now."""


class DocumentTooLargeError(ApiError):
    """413: over your plan's size limit."""


class InvalidRequestError(ApiError):
    """422: an unknown schema, a bad URL, …; see ``fields``."""


class QuotaExceededError(ApiError):
    """429: this month's validations are used up."""


class RateLimitedError(ApiError):
    """429: too many requests a minute, still so after the retries."""

    retry_after: int = 0
    """Seconds to wait before the next request."""


class ServerError(ApiError):
    """5xx: something broke on xmlvalid's side."""


class TransportError(XmlvalidError):
    """The request could not be sent, or its answer read."""


class ValidationTimeoutError(XmlvalidError, TimeoutError):
    """The validation was still running when the timeout ran out. It goes on on the server."""

    def __init__(self, validation: Validation, timeout: float) -> None:
        super().__init__(f"Validation {validation.id} was still {validation.status} after {timeout:g} seconds.")
        self.validation = validation


class SignatureVerificationError(XmlvalidError):
    """A webhook's signature is missing, too old or does not match."""
