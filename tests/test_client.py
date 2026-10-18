from __future__ import annotations

import io
import re

import httpx
import pytest

from xmlvalid import (
    ApiError,
    AuthenticationError,
    Client,
    InvalidRequestError,
    NotFinishedError,
    PlanLimitError,
    QuotaExceededError,
    RateLimitedError,
    ServerError,
    TransportError,
    Validation,
    ValidationTimeoutError,
)

from .conftest import FIXTURES, Api, Reads, validation


@pytest.fixture
def client(api: Api) -> Client:
    return Client("xv_test", http_client=httpx.Client(transport=httpx.MockTransport(api.handler)))


def test_a_file_is_sent_as_the_body(client: Client, api: Api) -> None:
    api.json(
        200,
        validation(
            errors=[{"line": 139, "level": "error", "type": "schematron", "rule": "BR-CO-16", "message": "Amount due"}]
        ),
    )

    result = client.validate(FIXTURES / "invoice.xml", schema="peppol-bis-3-invoice")

    request = api.requests[0]
    assert request.method == "POST"
    assert (
        str(request.url)
        == "https://xmlvalid.com/api/v1/validations?wait=10&name=invoice.xml&schema=peppol-bis-3-invoice"
    )
    assert request.headers["Authorization"] == "Bearer xv_test"
    assert request.headers["Content-Type"] == "application/xml"
    assert request.headers["User-Agent"].startswith("xmlvalid-python/1.0.0 Python/")
    assert api.bodies[0] == (FIXTURES / "invoice.xml").read_bytes()
    assert result.id == "val_1"
    assert result.report_url == "https://xmlvalid.com/api/v1/validations/val_1/report"
    assert [str(error) for error in result.errors] == ["Line 139: [BR-CO-16] Amount due"]


def test_text_bytes_and_file_objects(client: Client, api: Api) -> None:
    api.json(200, validation()).json(200, validation()).json(200, validation())

    client.validate(text="<a/>", doctype=True)
    client.validate(b"PK\x03\x04", name="batch.zip")
    with open(FIXTURES / "invoice.xsd", "rb") as handle:
        client.validate(handle)

    assert api.bodies[0] == b"<a/>"
    assert api.requests[0].url.params["doctype"] == "1"
    assert api.requests[0].url.params["name"] == "document.xml"
    assert api.requests[1].url.params["name"] == "batch.zip"
    assert api.requests[1].headers["Content-Type"] == "application/octet-stream"
    assert api.requests[2].url.params["name"] == "invoice.xsd"


def test_a_large_document_is_streamed(client: Client, api: Api) -> None:
    api.json(200, validation())
    large = b"<a>" + b"x" * (3 << 20) + b"</a>"

    document = Reads(large)
    client.validate(document, name="large.xml")

    assert document.streamed
    assert api.requests[0].headers["Content-Length"] == str(len(large))
    assert api.bodies[0] == large


def test_a_url_is_sent_as_json(client: Client, api: Api) -> None:
    api.json(200, validation())

    client.validate(url="https://example.com/feed.xml", schema="auto")

    assert api.requests[0].headers["Content-Type"] == "application/json"
    assert api.bodies[0] == b'{"url":"https://example.com/feed.xml","wait":10,"schema":"auto"}'


def test_own_schema_and_rules_go_as_multipart(client: Client, api: Api) -> None:
    api.json(200, validation())

    client.validate(
        text="<a/>",
        schema_file=FIXTURES / "invoice.xsd",
        rules={"main.sch": FIXTURES / "main.sch", "parts/totals.sch": FIXTURES / "totals.sch"},
        doctype=True,
    )

    body = api.bodies[0].decode()
    assert api.requests[0].headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert re.search(r'name="document"; filename="document.xml"\r\nContent-Type: application/xml\r\n\r\n<a/>', body)
    assert 'name="schema_file"; filename="invoice.xsd"' in body
    assert body.count('name="rules_file[]"') == 2
    assert 'filename="totals.sch"' in body
    assert re.search(r'name="rules_path\[\]"\r\n\r\nmain.sch\r\n', body)
    assert re.search(r'name="rules_path\[\]"\r\n\r\nparts/totals.sch\r\n', body)
    assert re.search(r'name="doctype"\r\n\r\n1\r\n', body)


def test_a_single_rules_file(client: Client, api: Api) -> None:
    api.json(200, validation())

    client.validate(url="https://example.com/a.xml", rules=FIXTURES / "main.sch")

    body = api.bodies[0].decode()
    assert re.search(r'name="url"\r\n\r\nhttps://example.com/a.xml\r\n', body)
    assert 'name="rules_file"; filename="main.sch"' in body


def test_it_polls_until_finished(client: Client, api: Api, sleeps: list[float]) -> None:
    api.json(202, validation("queued")).json(200, validation("running")).json(200, validation())

    result = client.validate(text="<a/>")

    assert result.is_finished and result.is_valid
    assert sleeps == [1.0, 1.5]
    assert str(api.requests[2].url) == "https://xmlvalid.com/api/v1/validations/val_1"


def test_a_timeout_carries_the_validation(client: Client, api: Api, sleeps: list[float]) -> None:
    api.json(202, validation("queued"))

    with pytest.raises(ValidationTimeoutError) as raised:
        client.validate(text="<a/>", timeout=0)

    assert raised.value.validation.status == "queued"
    assert "val_1 was still queued after 0 seconds" in str(raised.value)


def test_submit_answers_at_once(client: Client, api: Api) -> None:
    api.json(202, validation("queued"))

    result = client.submit(text="<a/>", schema="ubl-2.1-invoice")

    assert result.status == "queued" and not result.is_finished
    assert api.requests[0].url.params["wait"] == "0"


def test_rate_limited_requests_are_retried(client: Client, api: Api, sleeps: list[float]) -> None:
    limited = {"error": {"code": "rate_limited", "message": "Too many requests."}}
    api.json(429, limited, {"Retry-After": "7"}).json(200, validation())

    assert client.validate(FIXTURES / "invoice.xml").is_valid

    assert sleeps == [7.0]
    assert api.bodies[1] == (FIXTURES / "invoice.xml").read_bytes()


def test_retries_end_and_unreadable_streams_are_not_retried(api: Api, sleeps: list[float]) -> None:
    client = Client("xv_test", max_retries=1, http_client=httpx.Client(transport=httpx.MockTransport(api.handler)))
    limited = {"error": {"code": "rate_limited", "message": "Too many requests."}}
    api.json(429, limited, {"Retry-After": "3"}).json(429, limited, {"Retry-After": "3"}).json(429, limited)

    with pytest.raises(RateLimitedError) as raised:
        client.usage()
    assert raised.value.retry_after == 3
    assert sleeps == [3.0]

    class Pipe(io.RawIOBase):
        def readable(self) -> bool:
            return True

        def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
            return 0

    with pytest.raises(RateLimitedError):
        client.validate(io.BufferedReader(Pipe()))
    assert sleeps == [3.0]


def test_quota_is_not_retried(client: Client, api: Api, sleeps: list[float]) -> None:
    api.json(429, {"error": {"code": "quota_exceeded", "message": "This month's validations are used up."}})

    with pytest.raises(QuotaExceededError, match="used up"):
        client.usage()
    assert sleeps == []


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, AuthenticationError), (403, PlanLimitError), (409, NotFinishedError), (418, ApiError)],
)
def test_errors_by_status(client: Client, api: Api, status: int, kind: type[ApiError]) -> None:
    api.json(status, {"error": {"code": "some_code", "message": "No."}})

    with pytest.raises(kind) as raised:
        client.usage()
    assert raised.value.status_code == status
    assert raised.value.error_code == "some_code"


def test_invalid_request_lists_fields_and_a_server_error_has_a_message(client: Client, api: Api) -> None:
    api.json(
        422, {"error": {"code": "invalid_request", "message": "Check the fields.", "fields": {"schema": ["Unknown."]}}}
    )
    api.raw(502, "<html>Bad gateway</html>")

    with pytest.raises(InvalidRequestError) as invalid:
        client.validate(text="<a/>", schema="nope")
    assert invalid.value.fields == {"schema": ["Unknown."]}

    with pytest.raises(ServerError, match=r"xmlvalid answered HTTP 502\.") as server:
        client.usage()
    assert server.value.error_code == "server_error"


def test_transport_failures_and_non_json(client: Client, api: Api) -> None:
    api.fail(httpx.ConnectError("Could not resolve host")).raw(200, "not json")

    with pytest.raises(TransportError, match="Could not resolve host"):
        client.usage()
    with pytest.raises(TransportError, match="something other than JSON"):
        client.usage()


def test_fetch_cancel_report_and_share(client: Client, api: Api) -> None:
    api.json(200, validation()).json(200, validation("cancelled")).raw(200, "<html>Report</html>")
    api.json(201, {"url": "https://xmlvalid.com/reports/01abc", "expires_at": "2026-11-17T10:00:00+00:00"})

    assert client.validation("val_1").is_valid
    assert client.cancel("val_1").status == "cancelled"
    assert client.report("val_1") == "<html>Report</html>"
    link = client.share(["val_1", Validation.from_dict({**validation(), "id": "val_2"})])

    assert [(request.method, request.url.path) for request in api.requests] == [
        ("GET", "/api/v1/validations/val_1"),
        ("DELETE", "/api/v1/validations/val_1"),
        ("GET", "/api/v1/validations/val_1/report"),
        ("POST", "/api/v1/reports"),
    ]
    assert api.requests[2].headers["Accept"] == "text/html"
    assert api.bodies[3] == b'{"validations":["val_1","val_2"]}'
    assert link.url == "https://xmlvalid.com/reports/01abc"
    assert link.expires_at is not None and link.expires_at.year == 2026


def test_usage_and_schemas(client: Client, api: Api) -> None:
    api.json(200, {
        "plan": "pro",
        "period": {"start": "2026-10-01T00:00:00+00:00", "reset_at": "2026-11-01T00:00:00+00:00"},
        "validations": {"used": 3, "limit": 10000},
        "limits": {"max_file_bytes": 524288000, "requests_per_minute": 120},
    })  # fmt: skip
    api.json(200, {
        "saved": [{"schema": "my-12", "name": "order.xsd", "kind": "xsd", "namespace": "urn:example:order"}],
        "catalog": [{
            "schema": "peppol-bis-3-invoice", "name": "Peppol BIS Billing 3.0 Invoice", "kind": "xsd",
            "namespace": None, "version": "3.0.20", "rules": ["EN 16931"],
        }],
    })  # fmt: skip

    usage = client.usage()
    schemas = client.schemas()

    assert (usage.plan, usage.remaining, usage.requests_per_minute) == ("pro", 9997, 120)
    assert [(schema.schema, schema.saved, schema.rules) for schema in schemas] == [
        ("my-12", True, []),
        ("peppol-bis-3-invoice", False, ["EN 16931"]),
    ]


def test_the_key_and_the_document_are_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XMLVALID_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key"):
        Client()

    monkeypatch.setenv("XMLVALID_API_KEY", "xv_env")
    client = Client()
    with pytest.raises(ValueError, match="Cannot read the file"):
        client.validate("missing.xml")
    with pytest.raises(ValueError, match="one of document"):
        client.validate(text="<a/>", url="https://example.com/a.xml")
    client.close()
