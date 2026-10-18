"""Python client for the xmlvalid API: https://xmlvalid.com/docs/api"""

from . import webhooks
from ._client import DEFAULT_BASE_URL, AsyncClient, Client, DocumentInput, Rules
from ._version import __version__
from .errors import (
    ApiError,
    AuthenticationError,
    DocumentTooLargeError,
    InvalidRequestError,
    NotFinishedError,
    NotFoundError,
    PlanLimitError,
    QuotaExceededError,
    RateLimitedError,
    ServerError,
    SignatureVerificationError,
    TransportError,
    ValidationTimeoutError,
    XmlvalidError,
)
from .models import ArchiveItem, Diagnostic, Event, ReportLink, Result, Schema, Usage, Validation

__all__ = [
    "DEFAULT_BASE_URL",
    "ApiError",
    "ArchiveItem",
    "AsyncClient",
    "AuthenticationError",
    "Client",
    "Diagnostic",
    "DocumentInput",
    "DocumentTooLargeError",
    "Event",
    "InvalidRequestError",
    "NotFinishedError",
    "NotFoundError",
    "PlanLimitError",
    "QuotaExceededError",
    "RateLimitedError",
    "ReportLink",
    "Result",
    "Rules",
    "Schema",
    "ServerError",
    "SignatureVerificationError",
    "TransportError",
    "Usage",
    "Validation",
    "ValidationTimeoutError",
    "XmlvalidError",
    "__version__",
    "webhooks",
]
