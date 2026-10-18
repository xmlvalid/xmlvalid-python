from __future__ import annotations

import io
import os
import platform
import time
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import IO, Any
from urllib.parse import quote

import anyio
import httpx

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
    TransportError,
    ValidationTimeoutError,
)
from .models import ReportLink, Schema, Usage, Validation

DEFAULT_BASE_URL = "https://xmlvalid.com/api/v1"

DocumentInput = str | os.PathLike[str] | bytes | IO[bytes]
"""A file path, the document's bytes, or a binary file object."""

Rules = str | os.PathLike[str] | Mapping[str, str | os.PathLike[str]]
"""Your own Schematron: a .sch file, or {relative path: file} for one with includes."""

_XML_EXTENSIONS = (".xml", ".xsd", ".sch", ".rng", ".xsl", ".xslt", ".svg", ".xhtml", ".gpx", ".kml")
_CHUNK = 1 << 16
_BUFFER = 1 << 21


class _Document:
    """The document to validate, readable again for a retry when it can be."""

    def __init__(self, document: DocumentInput | None, text: str | None, url: str | None, name: str | None) -> None:
        if sum(value is not None for value in (document, text, url)) != 1:
            raise ValueError("Pass one of document, text= or url=.")

        self.url = url
        self.path: str | None = None
        self.data: bytes | None = None
        self.stream: IO[bytes] | None = None
        self.start = 0

        if text is not None:
            self.data = text.encode()
        elif isinstance(document, bytes):
            self.data = document
        elif isinstance(document, (str, os.PathLike)):
            self.path = os.fspath(document)
            if not os.path.isfile(self.path):
                raise ValueError(f"Cannot read the file {self.path}.")
        elif document is not None:
            self.stream = document
            self.start = document.tell() if document.seekable() else 0

        default = os.path.basename(self.path or str(getattr(self.stream, "name", "")) or "") or "document.xml"
        self.name = name or (os.path.basename(url.split("?")[0]) if url else default)

    @property
    def size(self) -> int | None:
        if self.data is not None:
            return len(self.data)
        if self.path is not None:
            return os.path.getsize(self.path)
        if self.stream is not None and self.stream.seekable():
            end = self.stream.seek(0, io.SEEK_END)
            self.stream.seek(self.start)
            return end - self.start
        return None

    @property
    def rereadable(self) -> bool:
        return self.stream is None or self.stream.seekable()

    @property
    def content_type(self) -> str:
        return "application/xml" if self.name.lower().endswith(_XML_EXTENSIONS) else "application/octet-stream"

    def open(self) -> tuple[IO[bytes], bool]:
        """A file object at the document's start, and whether the caller closes it."""
        if self.data is not None:
            return io.BytesIO(self.data), True
        if self.path is not None:
            return open(self.path, "rb"), True
        assert self.stream is not None
        if self.stream.seekable():
            self.stream.seek(self.start)
        return self.stream, False


@dataclass
class _Call:
    """A request, built afresh for each attempt."""

    method: str
    path: str
    params: dict[str, str | list[str]] = field(default_factory=dict)
    json: Any = None
    accept: str = "application/json"
    document: _Document | None = None
    """Sent as the raw body."""
    form: dict[str, str | list[str]] | None = None
    files: list[tuple[str, tuple[str, str | _Document, str]]] | None = None
    """Multipart parts: (field, (filename, path or document, content type))."""

    @property
    def retryable(self) -> bool:
        documents = [self.document] if self.document is not None else []
        documents += [source for _, (_, source, _) in self.files or [] if isinstance(source, _Document)]
        return all(document.rereadable for document in documents)


class _BaseClient:
    def __init__(self, api_key: str, base_url: str, timeout: float, wait: int, max_retries: int) -> None:
        if not api_key:
            raise ValueError("An API key (xv_…) from https://xmlvalid.com/dashboard/api is needed.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._wait = max(0, min(60, wait))
        self._max_retries = max_retries

    def _headers(self, accept: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": accept,
            "User-Agent": f"xmlvalid-python/{__version__} Python/{platform.python_version()}",
        }

    def _submit_call(
        self,
        document: _Document,
        schema: str | None,
        schema_file: str | os.PathLike[str] | None,
        doctype: bool,
        rules: Rules | None,
        rules_version: str | Sequence[str] | None,
        wait: int,
    ) -> _Call:
        wait = max(0, min(60, wait))
        pins = [rules_version] if isinstance(rules_version, str) else list(rules_version or [])
        if schema_file is not None or rules is not None:
            return self._multipart_call(document, schema, schema_file, doctype, rules, pins, wait)
        if document.url is not None:
            body: dict[str, Any] = {"url": document.url, "wait": wait}
            if schema is not None:
                body["schema"] = schema
            if doctype:
                body["doctype"] = True
            if pins:
                body["rules_version"] = pins
            return _Call("POST", "/validations", json=body)

        params: dict[str, str | list[str]] = {"wait": str(wait), "name": document.name}
        if schema is not None:
            params["schema"] = schema
        if doctype:
            params["doctype"] = "1"
        if pins:
            params["rules_version[]"] = pins
        return _Call("POST", "/validations", params=params, document=document)

    @staticmethod
    def _multipart_call(
        document: _Document,
        schema: str | None,
        schema_file: str | os.PathLike[str] | None,
        doctype: bool,
        rules: Rules | None,
        pins: list[str],
        wait: int,
    ) -> _Call:
        form: dict[str, str | list[str]] = {"wait": str(wait)}
        files: list[tuple[str, tuple[str, str | _Document, str]]] = []
        if document.url is not None:
            form["url"] = document.url
        else:
            files.append(("document", (document.name, document, document.content_type)))
        if schema is not None:
            form["schema"] = schema
        if doctype:
            form["doctype"] = "1"
        if pins:
            form["rules_version[]"] = pins

        def part(path: str | os.PathLike[str], filename: str | None = None) -> tuple[str, str | _Document, str]:
            path = os.fspath(path)
            if not os.path.isfile(path):
                raise ValueError(f"Cannot read the file {path}.")
            return filename or os.path.basename(path), path, "application/octet-stream"

        if schema_file is not None:
            files.append(("schema_file", part(schema_file)))
        if isinstance(rules, Mapping):
            paths = list(rules)
            files += [("rules_file[]", part(rules[relative], os.path.basename(relative))) for relative in paths]
            # httpx sends a list as repeated fields; rules_path[] pairs with rules_file[] by position.
            form["rules_path[]"] = paths
            return _Call("POST", "/validations", form=form, files=files)
        if rules is not None:
            files.append(("rules_file", part(rules)))
        return _Call("POST", "/validations", form=form, files=files)

    @staticmethod
    def _id(validation: Validation | str) -> str:
        return validation if isinstance(validation, str) else validation.id

    @staticmethod
    def _path(id: str, suffix: str = "") -> str:
        return f"/validations/{quote(id, safe='')}{suffix}"

    @staticmethod
    def _error(response: httpx.Response) -> ApiError:
        status = response.status_code
        try:
            data = response.json()
        except ValueError:
            data = None
        error = data.get("error") if isinstance(data, dict) else None
        error = error if isinstance(error, dict) else {}
        code = error.get("code")
        code = code if isinstance(code, str) else ("server_error" if status >= 500 else "http_error")
        message = error.get("message")
        fields = error.get("fields")
        problems = {
            str(name): [str(item) for item in value] if isinstance(value, list) else []
            for name, value in (fields.items() if isinstance(fields, dict) else [])
        }

        kind: type[ApiError] = ApiError
        if status == 401:
            kind = AuthenticationError
        elif status == 403:
            kind = PlanLimitError
        elif status == 404:
            kind = NotFoundError
        elif status == 409:
            kind = RulesVersionMismatchError if code == "rules_version_mismatch" else NotFinishedError
        elif status == 413:
            kind = DocumentTooLargeError
        elif status == 422:
            kind = InvalidRequestError
        elif status == 429:
            kind = QuotaExceededError if code == "quota_exceeded" else RateLimitedError
        elif status >= 500:
            kind = ServerError

        text = message if isinstance(message, str) and message else f"xmlvalid answered HTTP {status}."
        exception = kind(text, status, code, problems)
        if isinstance(exception, RateLimitedError):
            retry_after = response.headers.get("Retry-After", "")
            exception.retry_after = int(retry_after) if retry_after.isdigit() else 0
        if isinstance(exception, RulesVersionMismatchError):
            exception.rule_set = str(error.get("rule_set") or "")
            exception.pinned = str(error.get("pinned") or "")
            exception.current = str(error.get("current") or "")
        return exception

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as e:
            raise TransportError("xmlvalid answered with something other than JSON.") from e
        if not isinstance(data, dict):
            raise TransportError("xmlvalid answered with something other than a JSON object.")
        return {str(key): value for key, value in data.items()}

    @staticmethod
    def _schemas(data: dict[str, Any]) -> list[Schema]:
        def entries(key: str) -> list[dict[str, Any]]:
            value = data.get(key)
            return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

        return [Schema.from_dict(item, True) for item in entries("saved")] + [
            Schema.from_dict(item, False) for item in entries("catalog")
        ]

    def _retry_delay(self, error: ApiError, attempt: int, call: _Call) -> float | None:
        """Seconds to wait before retrying, or None to raise the error."""
        if isinstance(error, RateLimitedError) and attempt < self._max_retries and call.retryable:
            return float(max(1, min(60, error.retry_after)))
        return None


class Client(_BaseClient):
    """Client for the xmlvalid API (https://xmlvalid.com/docs/api).

    ::

        from xmlvalid import Client

        xmlvalid = Client("xv_…")
        validation = xmlvalid.validate("invoice.xml", schema="peppol-bis-3-invoice")
        for error in validation.errors:
            print(error)  # Line 139: [BR-CO-16] Amount due for payment …

    :param api_key: An API key (xv_…) from https://xmlvalid.com/dashboard/api
    :param timeout: Seconds :meth:`validate` waits for a result in all
    :param wait: Seconds the API holds a new validation's request before answering with its status (0-60)
    :param max_retries: Times a request refused with 429 rate_limited is retried, after Retry-After
    :param http_client: An ``httpx.Client`` of your own (proxies, certificates, transports)
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 900,
        wait: int = 10,
        max_retries: int = 3,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(api_key or os.environ.get("XMLVALID_API_KEY", ""), base_url, timeout, wait, max_retries)
        self._http = http_client or httpx.Client(timeout=httpx.Timeout(120, connect=10))
        self._owns_http = http_client is None

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def validate(
        self,
        document: DocumentInput | None = None,
        *,
        text: str | None = None,
        url: str | None = None,
        name: str | None = None,
        schema: str | None = None,
        schema_file: str | os.PathLike[str] | None = None,
        rules: Rules | None = None,
        rules_version: str | Sequence[str] | None = None,
        doctype: bool = False,
        timeout: float | None = None,
    ) -> Validation:
        """Validates a document and waits for the result.

        :param document: A file path (XML, .gz, .zip, EPUB, Factur-X PDF), the document's bytes, or a binary file object
        :param text: The document as a string, instead
        :param url: A public http(s) address xmlvalid downloads itself, instead
        :param name: The document's name in results and reports (default: the file's)
        :param schema: A catalog slug (peppol-bis-3-invoice), a saved schema (my-12), "auto" for the profile
            an e-invoice names, or None to check well-formedness only
        :param schema_file: An XSD, DTD or RelaxNG file to validate against instead
        :param rules: Your own Schematron, run after the schema check
        :param rules_version: Rule set releases the check was written against, as ``rule-set@version``
            (peppol-bis-3-ubl@3.0.21), one or several
        :param doctype: Validate against the DTD the DOCTYPE names
        :param timeout: Seconds to wait in all (default: the client's)
        :raises ValidationTimeoutError: when it is still running after ``timeout``
        :raises RulesVersionMismatchError: when a pinned rule set runs another release now
        """
        timeout = self._timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        validation = self.submit(
            document, text=text, url=url, name=name, schema=schema, schema_file=schema_file,
            rules=rules, rules_version=rules_version, doctype=doctype, wait=int(min(self._wait, max(0, timeout))),
        )  # fmt: skip
        return self.wait_for(validation, timeout=max(0.0, deadline - time.monotonic()))

    def submit(
        self,
        document: DocumentInput | None = None,
        *,
        text: str | None = None,
        url: str | None = None,
        name: str | None = None,
        schema: str | None = None,
        schema_file: str | os.PathLike[str] | None = None,
        rules: Rules | None = None,
        rules_version: str | Sequence[str] | None = None,
        doctype: bool = False,
        wait: int = 0,
    ) -> Validation:
        """Queues a validation and returns it at once (or after ``wait`` seconds, if it is done by then)."""
        call = self._submit_call(
            _Document(document, text, url, name), schema, schema_file, doctype, rules, rules_version, wait
        )
        return Validation.from_dict(self._decode(self._send(call)))

    def wait_for(self, validation: Validation | str, *, timeout: float | None = None) -> Validation:
        """Waits until a validation has finished, polling its status.

        :raises ValidationTimeoutError: when it is still running after ``timeout``
        """
        timeout = self._timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        current = self.validation(validation) if isinstance(validation, str) else validation
        interval = 1.0
        while not current.is_finished:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ValidationTimeoutError(current, timeout)
            time.sleep(min(interval, left))
            interval = min(5.0, interval * 1.5)
            current = self.validation(current.id)
        return current

    def validation(self, id: str) -> Validation:
        """A validation by its id (val_…)."""
        return Validation.from_dict(self._decode(self._send(_Call("GET", self._path(id)))))

    def cancel(self, validation: Validation | str) -> Validation:
        """Cancels a queued or running validation."""
        return Validation.from_dict(self._decode(self._send(_Call("DELETE", self._path(self._id(validation))))))

    def report(self, validation: Validation | str) -> str:
        """The result as an HTML page."""
        return self._send(_Call("GET", self._path(self._id(validation), "/report"), accept="text/html")).text

    def share(self, validations: Sequence[Validation | str]) -> ReportLink:
        """A public link to the report of one or more validations, for 30 days (Pro)."""
        body = {"validations": [self._id(validation) for validation in validations]}
        return ReportLink.from_dict(self._decode(self._send(_Call("POST", "/reports", json=body))))

    def usage(self) -> Usage:
        """This month's validations and the plan's limits."""
        return Usage.from_dict(self._decode(self._send(_Call("GET", "/usage"))))

    def schemas(self) -> list[Schema]:
        """The account's saved schemas, then the public catalog."""
        return self._schemas(self._decode(self._send(_Call("GET", "/schemas"))))

    def _send(self, call: _Call) -> httpx.Response:
        attempt = 0
        while True:
            opened: list[IO[bytes]] = []
            try:
                response = self._http.request(call.method, self._base_url + call.path, **self._options(call, opened))
            except httpx.TransportError as e:
                raise TransportError(f"Request to xmlvalid failed: {e}") from e
            finally:
                for handle in opened:
                    handle.close()

            if response.status_code < 400:
                return response
            error = self._error(response)
            delay = self._retry_delay(error, attempt, call)
            if delay is None:
                raise error
            time.sleep(delay)
            attempt += 1

    def _options(self, call: _Call, opened: list[IO[bytes]]) -> dict[str, Any]:
        options: dict[str, Any] = {"headers": self._headers(call.accept), "params": call.params}
        if call.json is not None:
            options["json"] = call.json
        if call.document is not None:
            handle, owned = call.document.open()
            if owned:
                opened.append(handle)
            size = call.document.size
            options["headers"]["Content-Type"] = call.document.content_type
            if size is not None:
                options["headers"]["Content-Length"] = str(size)
            options["content"] = handle.read() if size is not None and size <= _BUFFER else _chunks(handle)
        if call.files is not None:
            options["data"] = call.form
            options["files"] = [
                (name, (filename, _part(source, opened), kind)) for name, (filename, source, kind) in call.files
            ]
        return options


class AsyncClient(_BaseClient):
    """The same as :class:`Client`, for asyncio and trio.

    ::

        async with AsyncClient("xv_…") as xmlvalid:
            validation = await xmlvalid.validate("invoice.xml", schema="peppol-bis-3-invoice")
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 900,
        wait: int = 10,
        max_retries: int = 3,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key or os.environ.get("XMLVALID_API_KEY", ""), base_url, timeout, wait, max_retries)
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))
        self._owns_http = http_client is None

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def validate(
        self,
        document: DocumentInput | None = None,
        *,
        text: str | None = None,
        url: str | None = None,
        name: str | None = None,
        schema: str | None = None,
        schema_file: str | os.PathLike[str] | None = None,
        rules: Rules | None = None,
        rules_version: str | Sequence[str] | None = None,
        doctype: bool = False,
        timeout: float | None = None,
    ) -> Validation:
        """Validates a document and waits for the result; see :meth:`Client.validate`."""
        timeout = self._timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        validation = await self.submit(
            document, text=text, url=url, name=name, schema=schema, schema_file=schema_file,
            rules=rules, rules_version=rules_version, doctype=doctype, wait=int(min(self._wait, max(0, timeout))),
        )  # fmt: skip
        return await self.wait_for(validation, timeout=max(0.0, deadline - time.monotonic()))

    async def submit(
        self,
        document: DocumentInput | None = None,
        *,
        text: str | None = None,
        url: str | None = None,
        name: str | None = None,
        schema: str | None = None,
        schema_file: str | os.PathLike[str] | None = None,
        rules: Rules | None = None,
        rules_version: str | Sequence[str] | None = None,
        doctype: bool = False,
        wait: int = 0,
    ) -> Validation:
        """Queues a validation and returns it at once; see :meth:`Client.submit`."""
        call = self._submit_call(
            _Document(document, text, url, name), schema, schema_file, doctype, rules, rules_version, wait
        )
        return Validation.from_dict(self._decode(await self._send(call)))

    async def wait_for(self, validation: Validation | str, *, timeout: float | None = None) -> Validation:
        """Waits until a validation has finished, polling its status."""
        timeout = self._timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        current = await self.validation(validation) if isinstance(validation, str) else validation
        interval = 1.0
        while not current.is_finished:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ValidationTimeoutError(current, timeout)
            await anyio.sleep(min(interval, left))
            interval = min(5.0, interval * 1.5)
            current = await self.validation(current.id)
        return current

    async def validation(self, id: str) -> Validation:
        return Validation.from_dict(self._decode(await self._send(_Call("GET", self._path(id)))))

    async def cancel(self, validation: Validation | str) -> Validation:
        return Validation.from_dict(self._decode(await self._send(_Call("DELETE", self._path(self._id(validation))))))

    async def report(self, validation: Validation | str) -> str:
        return (await self._send(_Call("GET", self._path(self._id(validation), "/report"), accept="text/html"))).text

    async def share(self, validations: Sequence[Validation | str]) -> ReportLink:
        body = {"validations": [self._id(validation) for validation in validations]}
        return ReportLink.from_dict(self._decode(await self._send(_Call("POST", "/reports", json=body))))

    async def usage(self) -> Usage:
        return Usage.from_dict(self._decode(await self._send(_Call("GET", "/usage"))))

    async def schemas(self) -> list[Schema]:
        return self._schemas(self._decode(await self._send(_Call("GET", "/schemas"))))

    async def _send(self, call: _Call) -> httpx.Response:
        attempt = 0
        while True:
            opened: list[IO[bytes]] = []
            try:
                response = await self._http.request(
                    call.method, self._base_url + call.path, **self._options(call, opened)
                )
            except httpx.TransportError as e:
                raise TransportError(f"Request to xmlvalid failed: {e}") from e
            finally:
                for handle in opened:
                    handle.close()

            if response.status_code < 400:
                return response
            error = self._error(response)
            delay = self._retry_delay(error, attempt, call)
            if delay is None:
                raise error
            await anyio.sleep(delay)
            attempt += 1

    def _options(self, call: _Call, opened: list[IO[bytes]]) -> dict[str, Any]:
        options: dict[str, Any] = {"headers": self._headers(call.accept), "params": call.params}
        if call.json is not None:
            options["json"] = call.json
        if call.document is not None:
            handle, owned = call.document.open()
            if owned:
                opened.append(handle)
            size = call.document.size
            options["headers"]["Content-Type"] = call.document.content_type
            if size is not None:
                options["headers"]["Content-Length"] = str(size)
            options["content"] = handle.read() if size is not None and size <= _BUFFER else _async_chunks(handle)
        if call.files is not None:
            options["data"] = call.form
            options["files"] = [
                (name, (filename, _part(source, opened), kind)) for name, (filename, source, kind) in call.files
            ]
        return options


def _part(source: str | _Document, opened: list[IO[bytes]]) -> IO[bytes]:
    if isinstance(source, str):
        handle: IO[bytes] = open(source, "rb")  # noqa: SIM115 (closed once the request is sent)
        opened.append(handle)
        return handle
    handle, owned = source.open()
    if owned:
        opened.append(handle)
    return handle


def _chunks(handle: IO[bytes]) -> Iterator[bytes]:
    while chunk := handle.read(_CHUNK):
        yield chunk


async def _async_chunks(handle: IO[bytes]) -> AsyncIterator[bytes]:
    while chunk := handle.read(_CHUNK):
        yield chunk


__all__ = ["DEFAULT_BASE_URL", "AsyncClient", "Client", "DocumentInput", "Rules"]
