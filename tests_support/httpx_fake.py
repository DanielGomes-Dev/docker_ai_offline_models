"""Fake mínimo de `httpx.AsyncClient` para os testes (sem rede, sem respx)."""

from __future__ import annotations

import json as _json

import httpx


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text or _json.dumps(self._json)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=self)


class FakeAsyncClient:
    def __init__(self, responses=None, single=None, **_kwargs):
        self._responses = list(responses) if responses else None
        self._single = single
        self.calls: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _next(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        if self._responses is not None:
            return self._responses.pop(0)
        return self._single

    async def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)

    async def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)
