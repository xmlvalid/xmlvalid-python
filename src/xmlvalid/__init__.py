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
    RulesVersionMismatchError,
    ServerError,
    SignatureVerificationError,
    TransportError,
    ValidationTimeoutError,
    XmlvalidError,
)
from .models import ArchiveItem, Diagnostic, Engine, Event, ReportLink, Result, RuleSet, Schema, Usage, Validation

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
    "Engine",
    "Event",
    "InvalidRequestError",
    "NotFinishedError",
    "NotFoundError",
    "PlanLimitError",
    "QuotaExceededError",
    "RateLimitedError",
    "ReportLink",
    "Result",
    "RuleSet",
    "Rules",
    "RulesVersionMismatchError",
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
