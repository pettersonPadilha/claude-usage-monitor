"""HTTP client for the Claude usage endpoint (stdlib only)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from .config import (
    OAUTH_BETA_HEADER,
    REQUEST_TIMEOUT_SECONDS,
    USAGE_ENDPOINT,
    USER_AGENT,
)
from .credentials import Credentials, CredentialsError, load_credentials
from .model import UsageSnapshot, snapshot_from_payload

log = logging.getLogger(__name__)

HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429

# This endpoint answers 429 with "retry-after: 0", which is no help at all,
# so only a header asking for a real wait is worth honouring.
MIN_USEFUL_RETRY_AFTER = 30.0
MAX_USEFUL_RETRY_AFTER = 3600.0


class UsageError(RuntimeError):
    """A usage fetch failed.

    `needs_login` marks recoverable auth problems, `is_throttled` marks a
    429, and `retry_after` carries a server-supplied wait when it gave one.
    """

    def __init__(
        self,
        message: str,
        needs_login: bool = False,
        is_throttled: bool = False,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.needs_login = needs_login
        self.is_throttled = is_throttled
        self.retry_after = retry_after


def _retry_after_seconds(exc: urllib.error.HTTPError) -> Optional[float]:
    """Return the Retry-After wait, or None when the header is useless."""
    raw = exc.headers.get("Retry-After") if exc.headers else None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if seconds < MIN_USEFUL_RETRY_AFTER:
        return None
    return min(seconds, MAX_USEFUL_RETRY_AFTER)


def _request(token: str) -> dict:
    request = urllib.request.Request(
        USAGE_ENDPOINT,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": OAUTH_BETA_HEADER,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
            raise UsageError(
                "Login expirado. Rode `claude` para renovar.", needs_login=True
            ) from exc
        if exc.code == HTTP_TOO_MANY_REQUESTS:
            raise UsageError(
                "Consultas demais na API de uso.",
                is_throttled=True,
                retry_after=_retry_after_seconds(exc),
            ) from exc
        raise UsageError(f"A API de uso respondeu HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise UsageError(f"Sem conexão ({exc.reason}).") from exc
    except TimeoutError as exc:
        raise UsageError("A API de uso demorou demais para responder.") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise UsageError("A API de uso devolveu uma resposta malformada.") from exc

    if not isinstance(payload, dict):
        raise UsageError("A API de uso devolveu uma resposta inesperada.")
    return payload


def fetch_usage(credentials: Optional[Credentials] = None) -> UsageSnapshot:
    """Fetch the current usage snapshot. Raises UsageError on failure."""
    if credentials is None:
        try:
            credentials = load_credentials()
        except CredentialsError as exc:
            raise UsageError(str(exc), needs_login=True) from exc

    if credentials.is_expired:
        log.info("Access token is past its expiry; trying it anyway.")

    payload = _request(credentials.access_token)
    snapshot = snapshot_from_payload(
        payload, datetime.now(timezone.utc), credentials.plan_label
    )
    if snapshot.session is None and snapshot.week is None:
        raise UsageError("A API de uso não devolveu nenhuma janela de limite.")
    return snapshot
