"""A minimal public-REST transport with a hard read-only boundary."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx

from research.safety import (
    SENSITIVE_HEADER_NAMES,
    ResearchSafetyError,
    assert_no_trading_credentials,
)


class UnsafeResearchRequest(ResearchSafetyError):
    """Raised when a request falls outside the research network policy."""


class ReadOnlyTransport:
    """HTTPS GET/HEAD-only client for explicitly allowlisted public hosts."""

    def __init__(
        self,
        allowed_hosts: set[str] | frozenset[str],
        *,
        timeout_seconds: float = 15.0,
        client: Any | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        assert_no_trading_credentials(environ if environ is not None else os.environ)
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        if not self.allowed_hosts:
            raise UnsafeResearchRequest("at least one public host must be allowlisted")
        self._client = client or httpx.Client(timeout=httpx.Timeout(timeout_seconds))

    def _validate(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        body: object | None,
    ) -> None:
        if method.upper() not in {"GET", "HEAD"}:
            raise UnsafeResearchRequest(f"read-only transport rejects {method.upper()}")
        if body is not None:
            raise UnsafeResearchRequest("read-only transport rejects request bodies")

        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise UnsafeResearchRequest("only credential-free HTTPS URLs are allowed")
        if parsed.hostname.lower() not in self.allowed_hosts:
            raise UnsafeResearchRequest(f"host is not allowlisted: {parsed.hostname}")

        for key in (headers or {}):
            if key.lower() in SENSITIVE_HEADER_NAMES:
                raise UnsafeResearchRequest(f"trading/signing header rejected: {key}")

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        body: object | None = None,
    ) -> httpx.Response:
        self._validate(method, url, headers, body)
        safe_headers = {"Accept": "application/json", "User-Agent": "polymarket-bot-research/1"}
        safe_headers.update(headers or {})
        response = self._client.request(method.upper(), url, params=params, headers=safe_headers)
        response.raise_for_status()
        return response

    def get_json(self, url: str, *, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        payload = self.request("GET", url, params=params).json()
        if not isinstance(payload, dict):
            raise UnsafeResearchRequest("research endpoint returned a non-object JSON payload")
        return payload

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close:
            close()
