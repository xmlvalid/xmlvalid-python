# xmlvalid for Python

Python client for the [xmlvalid API](https://xmlvalid.com/docs/api): validate XML documents and
e-invoices against XSD, DTD, RelaxNG and Schematron business rules. Peppol BIS, XRechnung,
Factur-X / ZUGFeRD, EN 16931, UBL, CII and national rules (France, Italy, Croatia, Romania and
more) are in the [schema catalog](https://xmlvalid.com/schemas); your own schemas work too.

- Python 3.10+, sync and async (asyncio, trio), built on [httpx](https://www.python-httpx.org)
- Large files are streamed, not loaded into memory
- Waits for the result for you, retries when rate limited
- Typed results and exceptions, webhook signature checks

## Install

```bash
pip install xmlvalid
```

Create an API key under [Dashboard → API keys](https://xmlvalid.com/dashboard/api).

## Validate

```python
from xmlvalid import Client

xmlvalid = Client("xv_…")  # or set XMLVALID_API_KEY

validation = xmlvalid.validate("invoice.xml", schema="peppol-bis-3-invoice")

if validation.is_valid:
    print("Valid")
else:
    for error in validation.errors:
        print(error)  # Line 139: [BR-CO-16] Amount due for payment (BT-115) = …
```

The document can be:

```python
xmlvalid.validate("invoice.xml")  # a path (XML, .gz, .zip, EPUB, Factur-X PDF)
xmlvalid.validate(Path("invoice.xml"))  # a Path
xmlvalid.validate(data, name="invoice.xml")  # bytes
xmlvalid.validate(open("invoice.xml", "rb"))  # a binary file object
xmlvalid.validate(text="<Invoice>…</Invoice>")  # a string
xmlvalid.validate(url="https://example.com/feed.xml")  # a public URL, downloaded by xmlvalid
```

The schema:

| Argument | Validates against |
|---|---|
| `schema="peppol-bis-3-invoice"` | A [catalog](https://xmlvalid.com/schemas) entry, with its business rules |
| `schema="auto"` | The catalog profile an e-invoice names (BT-24), for mixed invoices |
| `schema="my-12"` | One of your saved schemas |
| `schema_file="order.xsd"` | An XSD, DTD or RelaxNG file sent with the document |
| `doctype=True` | The DOCTYPE the document declares |
| none | Well-formedness only |

Your own Schematron runs after the schema check: `rules="rules.sch"`, or for rules with
includes, relative path: file: `rules={"main.sch": "/path/main.sch", "parts/totals.sch": "/path/parts/totals.sch"}`.

Catalog business rules move to new releases. To fail instead of getting findings from rules
that changed, pin the releases a check was written against:

```python
xmlvalid.validate(
    "invoice.xml",
    schema="peppol-bis-3-invoice",
    rules_version=["peppol-bis-3-ubl@3.0.21", "en16931-ubl@1.3.16"],  # or one string
)
```

When a pinned rule set runs another release, a `RulesVersionMismatchError` is raised before
anything runs or counts against your quota. `xmlvalid.schemas()` lists each entry's `rule_sets`
with their keys and releases.

## Async

```python
from xmlvalid import AsyncClient

async with AsyncClient() as xmlvalid:
    validation = await xmlvalid.validate("invoice.xml", schema="xrechnung-3-ubl")
```

Every method of `Client` is there, awaited.

## The result

```python
validation.status  # done, failed (on xmlvalid's side) or cancelled
validation.result.outcome  # valid, warnings, invalid, schema, input or failed
validation.result.errors_total  # all of them; the first 500 are listed
for error in validation.errors:
    error.line, error.column, error.level, error.type  # xsd, schematron, …
    error.rule  # BR-CO-16 for a business rule
    error.message
    error.rule_url  # the rule's page on xmlvalid.com
    error.help_url  # how to fix this kind of error
validation.warnings
for rule_set in validation.rule_sets:  # the business rules that ran, with their releases
    rule_set.key, rule_set.version  # peppol-bis-3-ubl, 3.0.21
    rule_set.label  # Peppol BIS Billing 3.0 rules 3.0.21
    rule_set.pin  # peppol-bis-3-ubl@3.0.21, for rules_version=
validation.raw  # the API's JSON, as a dict
```

For a .zip, `validation.result.items` has one result per document (each with its own
`rule_sets`); for a PDF,
`validation.result.pdf` names the invoice found in it.

## Long validations, reports and the account

`validate()` waits up to 15 minutes (`timeout=`); a `ValidationTimeoutError` carries the
validation, which goes on on the server. To queue and come back later:

```python
validation = xmlvalid.submit("big.xml", schema="ubl-2.1-invoice")
# …
validation = xmlvalid.wait_for(validation.id)  # or xmlvalid.validation(id), xmlvalid.cancel(id)

html = xmlvalid.report(validation)  # the HTML report
link = xmlvalid.share([validation])  # a public link for 30 days (Pro): link.url

usage = xmlvalid.usage()  # usage.used, usage.limit, usage.remaining
schemas = xmlvalid.schemas()  # your saved schemas, then the catalog
```

## Errors

Every exception extends `xmlvalid.XmlvalidError`. API refusals are `ApiError`s with
`status_code`, `error_code` and, for `invalid_request`, `fields`:

| Exception | When |
|---|---|
| `AuthenticationError` | 401: no key, a revoked key |
| `PlanLimitError` | 403: not in your plan |
| `NotFoundError` | 404: no such validation, or it expired (24 hours) |
| `NotFinishedError` | 409: the report of a validation still running |
| `RulesVersionMismatchError` | 409: a pinned rule set runs another release; `rule_set`, `pinned`, `current` |
| `DocumentTooLargeError` | 413: over your plan's size limit |
| `InvalidRequestError` | 422: unknown schema, a bad URL, … |
| `QuotaExceededError` | 429: this month's validations are used up |
| `RateLimitedError` | 429: still limited after the retries; `retry_after` seconds |
| `ServerError` | 5xx |
| `TransportError` | The request could not be sent or its answer read |
| `ValidationTimeoutError` | Still running after `timeout=` (also a `TimeoutError`) |

## Webhooks

On Pro, xmlvalid can call your endpoint when a validation finishes or a URL monitor changes
state. Check the signature with the endpoint's secret and the raw body:

```python
from xmlvalid import Event, webhooks

event = webhooks.verify(
    request.body,  # the raw bytes, as received
    request.headers.get("Xmlvalid-Signature"),
    os.environ["XMLVALID_WEBHOOK_SECRET"],
)  # raises SignatureVerificationError

if event.type == Event.VALIDATION_COMPLETED:
    validation = event.validation
```

A retried delivery has the same `event.id`. The other events are `monitor.failed`,
`monitor.recovered` (`event.data["monitor"]`, `event.data["check"]`) and `ping`.

## Options

```python
Client(
    api_key="xv_…",  # default: XMLVALID_API_KEY
    base_url="https://xmlvalid.com/api/v1",
    timeout=900,  # seconds validate() waits in all
    wait=10,  # seconds the API holds a new request (0-60)
    max_retries=3,  # retries of a 429 rate_limited
    http_client=httpx.Client(...),  # proxies, certificates, a mock transport in tests
)
```

Use it as a context manager, or call `close()`, to close the connection pool.

## Development

```bash
uv sync
uv run pytest
uv run mypy
uv run ruff check && uv run ruff format --check
```

## License

MIT
