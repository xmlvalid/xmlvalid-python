"""What the API returns, as typed, read-only objects. Each keeps the JSON it came from in ``raw``."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

__all__ = [
    "ArchiveItem",
    "Diagnostic",
    "Engine",
    "Event",
    "ReportLink",
    "Result",
    "RuleSet",
    "Schema",
    "Usage",
    "Validation",
]


def _object(data: Any, key: str) -> dict[str, Any] | None:
    value = data.get(key) if isinstance(data, dict) else None
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else None


def _objects(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [{str(k): v for k, v in item.items()} for item in value if isinstance(item, dict)]


def _str(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key)
    return value if isinstance(value, str) else default


def _opt_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _bool(data: dict[str, Any], key: str) -> bool:
    return data.get(key) is True


def _date(data: dict[str, Any], key: str) -> datetime | None:
    value = data.get(key)
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class RuleSet:
    """A set of business rules a catalog schema runs, at the release in use."""

    key: str
    """What ``rules_version`` pins: peppol-bis-3-ubl."""
    name: str
    version: str
    """The release: 3.0.21."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuleSet:
        return cls(key=_str(data, "key"), name=_str(data, "name"), version=_str(data, "version"))

    @property
    def pin(self) -> str:
        """The pin for this release: ``peppol-bis-3-ubl@3.0.21``."""
        return f"{self.key}@{self.version}"

    @property
    def label(self) -> str:
        """Name and release, once: ``Peppol BIS Billing 3.0 rules 3.0.21``, ``EN 16931 rules 1.3.16 (UBL)``."""
        return self.name if self.version in self.name else f"{self.name} {self.version}"

    def __str__(self) -> str:
        return self.label


def _rule_sets(data: dict[str, Any]) -> list[RuleSet]:
    return [RuleSet.from_dict(item) for item in _objects(data, "rule_sets")]


@dataclass(frozen=True)
class Diagnostic:
    """One error or warning, with where it is and, when there is one, the rule that failed."""

    line: int
    """0 when the message is about the whole document."""
    column: int
    """0 when unknown; business rules point at an element's line only."""
    level: str
    """warning, error or fatal."""
    type: str
    """syntax, xsd, relaxng, dtd, schema, io, schematron (a business rule), archive or pdf."""
    message: str
    rule: str | None = None
    """The business rule that failed (BR-CO-15, PEPPOL-EN16931-R001) or the PDF check (PDF-AF)."""
    path: str | None = None
    """Where a business rule fired, as an XPath with the document's prefixes:
    ``/Invoice/cac:InvoiceLine[2]/cbc:LineExtensionAmount``."""
    message_en: str | None = None
    """The message in English, for a rule its publisher wrote in another language."""
    help_url: str | None = None
    """A page explaining this kind of error and how to fix it."""
    rule_url: str | None = None
    """The rule's page on xmlvalid.com."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Diagnostic:
        return cls(
            line=_int(data, "line"),
            column=_int(data, "column"),
            level=_str(data, "level", "error"),
            type=_str(data, "type"),
            message=_str(data, "message"),
            rule=_opt_str(data, "rule"),
            path=_opt_str(data, "path"),
            message_en=_opt_str(data, "message_en"),
            help_url=_opt_str(data, "help_url"),
            rule_url=_opt_str(data, "rule_url"),
        )

    @property
    def is_warning(self) -> bool:
        return self.level == "warning"

    def __str__(self) -> str:
        """``Line 139: [BR-CO-16] Amount due for payment …``"""
        line = f"Line {self.line}: " if self.line > 0 else ""
        rule = f"[{self.rule}] " if self.rule is not None else ""
        return f"{line}{rule}{self.message_en or self.message}"


@dataclass(frozen=True)
class Engine:
    """What checked a document, for an audit trail."""

    xmlvalid: str
    """The validation engine's version."""
    libxml2: str
    """The libxml2 of the schema check: 2.13.9."""
    saxonjs: str | None = None
    """The SaxonJS of the business rules; None when none ran."""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Engine | None:
        if data is None or _opt_str(data, "libxml2") is None:
            return None
        return cls(xmlvalid=_str(data, "xmlvalid"), libxml2=_str(data, "libxml2"), saxonjs=_opt_str(data, "saxonjs"))


@dataclass(frozen=True)
class ArchiveItem:
    """The result for one document of an archive."""

    name: str
    """Its path in the archive."""
    schema: str | None
    outcome: str
    """valid, warnings, invalid, schema, input, failed or skipped."""
    valid: bool
    errors_total: int
    warnings_total: int
    errors: list[Diagnostic]
    warnings: list[Diagnostic]
    note: str | None = None
    """Why a skipped document was left unchecked."""
    rule_sets: list[RuleSet] = field(default_factory=list)
    """The business rules its schema ran, with their releases."""
    sha256: str | None = None
    """SHA-256 of the document (of the PDF for a PDF invoice), in hex."""
    engine: Engine | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArchiveItem:
        return cls(
            name=_str(data, "name"),
            schema=_opt_str(data, "schema"),
            outcome=_str(data, "outcome"),
            valid=_bool(data, "valid"),
            errors_total=_int(data, "errors_total"),
            warnings_total=_int(data, "warnings_total"),
            errors=[Diagnostic.from_dict(item) for item in _objects(data, "errors")],
            warnings=[Diagnostic.from_dict(item) for item in _objects(data, "warnings")],
            note=_opt_str(data, "note"),
            rule_sets=_rule_sets(data),
            sha256=_opt_str(data, "sha256"),
            engine=Engine.from_dict(_object(data, "engine")),
        )


@dataclass(frozen=True)
class Result:
    """What a finished validation found."""

    valid: bool
    """True for the outcomes valid and warnings."""
    outcome: str
    """valid, warnings, invalid, schema (the schema can't be used), input (the document can't be read) or failed."""
    errors_total: int
    warnings_total: int
    errors_truncated: bool
    """More errors were found than are listed."""
    errors: list[Diagnostic]
    """The first 500."""
    warnings: list[Diagnostic]
    """The first 500."""
    bytes: int
    duration_ms: int
    pdf: dict[str, Any] | None = None
    """For a PDF: the invoice found in it (attachment, attachments, guideline, profile)."""
    documents: dict[str, Any] | None = None
    """For an archive: total, passed, failed, skipped."""
    items: list[ArchiveItem] = field(default_factory=list)
    """For an archive: one result per document."""
    sha256: str | None = None
    """SHA-256 of the file as sent (the PDF, the archive), in hex."""
    engine: Engine | None = None
    """What checked it: the libxml2 and, when business rules ran, the SaxonJS."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Result:
        return cls(
            valid=_bool(data, "valid"),
            outcome=_str(data, "outcome"),
            errors_total=_int(data, "errors_total"),
            warnings_total=_int(data, "warnings_total"),
            errors_truncated=_bool(data, "errors_truncated"),
            errors=[Diagnostic.from_dict(item) for item in _objects(data, "errors")],
            warnings=[Diagnostic.from_dict(item) for item in _objects(data, "warnings")],
            bytes=_int(data, "bytes"),
            duration_ms=_int(data, "duration_ms"),
            pdf=_object(data, "pdf"),
            documents=_object(data, "documents"),
            items=[ArchiveItem.from_dict(item) for item in _objects(data, "items")],
            sha256=_opt_str(data, "sha256"),
            engine=Engine.from_dict(_object(data, "engine")),
        )

    @property
    def first_error(self) -> Diagnostic | None:
        return self.errors[0] if self.errors else None


@dataclass(frozen=True)
class Validation:
    """A validation, finished or not. Results are kept for 24 hours."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    id: str
    """val_…"""
    status: str
    """queued, running, done, failed (on xmlvalid's side; see ``error``) or cancelled."""
    progress: int
    created_at: datetime | None
    finished_at: datetime | None
    document: dict[str, Any]
    """source, name, size, url."""
    schema: dict[str, Any] | None
    """kind, catalog, saved, detected, name."""
    result: Result | None
    error: str | None
    """What went wrong on xmlvalid's side when the status is failed."""
    report_url: str | None
    """The result as an HTML page, once finished (needs the API key)."""
    rule_sets: list[RuleSet] = field(default_factory=list)
    """The business rules the schema runs, with their releases (empty without any)."""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Validation:
        result = _object(data, "result")
        return cls(
            id=_str(data, "id"),
            status=_str(data, "status"),
            progress=_int(data, "progress"),
            created_at=_date(data, "created_at"),
            finished_at=_date(data, "finished_at"),
            document=_object(data, "document") or {},
            schema=_object(data, "schema"),
            result=Result.from_dict(result) if result is not None else None,
            error=_opt_str(data, "error"),
            report_url=_opt_str(_object(data, "links") or {}, "report"),
            rule_sets=_rule_sets(data),
            raw=data,
        )

    @property
    def is_finished(self) -> bool:
        """No longer queued or running."""
        return self.status not in (self.QUEUED, self.RUNNING)

    @property
    def is_valid(self) -> bool:
        """Finished, and the document passed (valid, or valid with warnings)."""
        return self.result is not None and self.result.valid

    @property
    def errors(self) -> list[Diagnostic]:
        """The errors found (empty while running)."""
        return self.result.errors if self.result is not None else []

    @property
    def warnings(self) -> list[Diagnostic]:
        """The warnings found (empty while running)."""
        return self.result.warnings if self.result is not None else []


@dataclass(frozen=True)
class Usage:
    """This month's validations and the plan's limits."""

    plan: str
    """free or pro."""
    period_start: datetime | None
    reset_at: datetime | None
    """When the count resets (the 1st of next month, UTC)."""
    used: int
    limit: int
    max_file_bytes: int
    requests_per_minute: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Usage:
        period = _object(data, "period") or {}
        validations = _object(data, "validations") or {}
        limits = _object(data, "limits") or {}
        return cls(
            plan=_str(data, "plan"),
            period_start=_date(period, "start"),
            reset_at=_date(period, "reset_at"),
            used=_int(validations, "used"),
            limit=_int(validations, "limit"),
            max_file_bytes=_int(limits, "max_file_bytes"),
            requests_per_minute=_int(limits, "requests_per_minute"),
        )

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


@dataclass(frozen=True)
class Schema:
    """A schema to validate against: one of the account's saved schemas or a catalog entry."""

    schema: str
    """The value to pass as schema: a catalog slug (peppol-bis-3-invoice) or a saved schema (my-12)."""
    name: str
    kind: str
    """xsd, dtd, rng or rnc."""
    namespace: str | None
    saved: bool
    version: str | None = None
    rules: list[str] = field(default_factory=list)
    """Schematron rule sets run after the schema check, in order."""
    rule_sets: list[RuleSet] = field(default_factory=list)
    """The same rule sets with their keys and releases, for ``rules_version``."""

    @classmethod
    def from_dict(cls, data: dict[str, Any], saved: bool) -> Schema:
        rules = data.get("rules")
        return cls(
            schema=_str(data, "schema"),
            name=_str(data, "name"),
            kind=_str(data, "kind"),
            namespace=_opt_str(data, "namespace"),
            saved=saved,
            version=_opt_str(data, "version"),
            rules=[rule for rule in rules if isinstance(rule, str)] if isinstance(rules, list) else [],
            rule_sets=_rule_sets(data),
        )


@dataclass(frozen=True)
class ReportLink:
    """A public link to a report, for 30 days."""

    url: str
    expires_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReportLink:
        return cls(url=_str(data, "url"), expires_at=_date(data, "expires_at"))


@dataclass(frozen=True)
class Event:
    """A webhook event: validation.completed, monitor.failed, monitor.recovered or ping.

    A retry carries the same id, so it can be used to skip events already handled.
    """

    VALIDATION_COMPLETED = "validation.completed"
    MONITOR_FAILED = "monitor.failed"
    MONITOR_RECOVERED = "monitor.recovered"
    PING = "ping"

    id: str
    type: str
    created_at: datetime | None
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Event:
        return cls(
            id=_str(payload, "id"),
            type=_str(payload, "type"),
            created_at=_date(payload, "created_at"),
            data=_object(payload, "data") or {},
        )

    @property
    def validation(self) -> Validation | None:
        """The validation of a validation.completed event; None for other events."""
        return Validation.from_dict(self.data) if self.type == self.VALIDATION_COMPLETED else None
