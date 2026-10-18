from __future__ import annotations

import asyncio
import re

import httpx
import pytest

from xmlvalid import AsyncClient, AuthenticationError, RulesVersionMismatchError

from .conftest import FIXTURES, Api, Reads, validation


def client(api: Api) -> AsyncClient:
    return AsyncClient("xv_test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(api.async_handler)))


def test_it_validates_and_polls(api: Api, sleeps: list[float]) -> None:
    api.json(202, validation("queued")).json(200, validation())

    async def run() -> bool:
        async with client(api) as xmlvalid:
            return (await xmlvalid.validate(FIXTURES / "invoice.xml", schema="peppol-bis-3-invoice")).is_valid

    assert asyncio.run(run())
    assert sleeps == [1.0]
    assert api.bodies[0] == (FIXTURES / "invoice.xml").read_bytes()


def test_a_large_document_is_streamed_and_multipart_works(api: Api) -> None:
    api.json(200, validation()).json(200, validation())
    large = b"<a>" + b"x" * (3 << 20) + b"</a>"
    document = Reads(large)

    async def run() -> None:
        xmlvalid = client(api)
        await xmlvalid.validate(document)
        await xmlvalid.validate(text="<a/>", schema_file=FIXTURES / "invoice.xsd", rules=FIXTURES / "main.sch")
        await xmlvalid.aclose()

    asyncio.run(run())

    assert document.streamed
    assert api.bodies[0] == large
    body = api.bodies[1].decode()
    assert re.search(r'name="document"; filename="document.xml"\r\nContent-Type: application/xml\r\n\r\n<a/>', body)
    assert 'name="rules_file"; filename="main.sch"' in body


def test_rules_version_and_a_mismatch(api: Api) -> None:
    api.json(200, validation()).json(200, validation()).json(200, validation())
    mismatch = {"code": "rules_version_mismatch", "message": "Update the pin.", "rule_set": "peppol-bis-3-ubl"}
    api.json(409, {"error": {**mismatch, "pinned": "3.0.1", "current": "3.0.21"}})

    async def run() -> RulesVersionMismatchError:
        async with client(api) as xmlvalid:
            await xmlvalid.validate(text="<a/>", rules_version="peppol-bis-3-ubl@3.0.21")
            await xmlvalid.submit(url="https://example.com/a.xml", rules_version=["peppol-bis-3-ubl@3.0.21"])
            await xmlvalid.submit(text="<a/>", rules=FIXTURES / "main.sch", rules_version=["peppol-bis-3-ubl@3.0.21"])
            with pytest.raises(RulesVersionMismatchError) as raised:
                await xmlvalid.submit(text="<a/>", rules_version="peppol-bis-3-ubl@3.0.1")
            return raised.value

    error = asyncio.run(run())

    assert api.requests[0].url.params.get_list("rules_version[]") == ["peppol-bis-3-ubl@3.0.21"]
    assert b'"rules_version":["peppol-bis-3-ubl@3.0.21"]' in api.bodies[1]
    assert re.search(r'name="rules_version\[\]"\r\n\r\npeppol-bis-3-ubl@3.0.21\r\n', api.bodies[2].decode())
    assert (error.rule_set, error.pinned, error.current) == ("peppol-bis-3-ubl", "3.0.1", "3.0.21")


def test_retries_and_errors(api: Api, sleeps: list[float]) -> None:
    api.json(429, {"error": {"code": "rate_limited", "message": "Slow down."}}, {"Retry-After": "2"})
    api.json(200, {"plan": "free", "validations": {"used": 1, "limit": 100}})
    api.json(401, {"error": {"code": "unauthenticated", "message": "The API key is not valid."}})

    async def run() -> int:
        xmlvalid = client(api)
        remaining = (await xmlvalid.usage()).remaining
        with pytest.raises(AuthenticationError):
            await xmlvalid.report("val_1")
        return remaining

    assert asyncio.run(run()) == 99
    assert sleeps == [2.0]
