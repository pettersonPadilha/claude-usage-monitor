"""Reads the Claude Code OAuth credentials written by the CLI.

The token is never logged, never copied elsewhere and is re-read on every
poll so that refreshes performed by Claude Code are picked up automatically.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import CREDENTIALS_PATH


class CredentialsError(RuntimeError):
    """Raised when no usable Claude Code credentials are available."""


@dataclass(frozen=True)
class Credentials:
    access_token: str
    subscription_type: str = ""
    rate_limit_tier: str = ""
    expires_at: Optional[datetime] = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= datetime.now(timezone.utc)

    @property
    def plan_label(self) -> str:
        return plan_label(self.subscription_type, self.rate_limit_tier)


# Tier strings look like "default_claude_max_5x" / "default_claude_max_20x".
_MULTIPLIERS = ("20x", "5x", "1x")

_PLAN_NAMES = {
    "team": "Team",
    "max": "Max",
    "pro": "Pro",
    "free": "Free",
    "enterprise": "Enterprise",
}


def plan_label(subscription_type: str, rate_limit_tier: str) -> str:
    """Human badge for the plan, e.g. "Team 5x"."""
    name = _PLAN_NAMES.get((subscription_type or "").strip().lower(), "")
    if not name and subscription_type:
        name = subscription_type.strip().replace("_", " ").title()

    tier = (rate_limit_tier or "").lower()
    multiplier = next((m for m in _MULTIPLIERS if m in tier), "")

    return " ".join(part for part in (name, multiplier) if part) or "Claude"


def _oauth_block(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CredentialsError("Formato inesperado no arquivo de credenciais.")
    block = raw.get("claudeAiOauth")
    if not isinstance(block, dict):
        raise CredentialsError(
            "Nenhum login de assinatura Claude encontrado. Rode `claude` e entre."
        )
    return block


def _expiry(value: Any) -> Optional[datetime]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def load_credentials(path: Path = CREDENTIALS_PATH) -> Credentials:
    """Load the OAuth credentials, raising CredentialsError when unusable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CredentialsError(
            f"{path} não encontrado. Faça login com `claude` primeiro."
        ) from exc
    except json.JSONDecodeError as exc:
        raise CredentialsError("O arquivo de credenciais não é um JSON válido.") from exc
    except OSError as exc:
        raise CredentialsError(f"Não foi possível ler as credenciais: {exc}") from exc

    block = _oauth_block(raw)
    token = block.get("accessToken")
    if not isinstance(token, str) or not token:
        raise CredentialsError("O arquivo de credenciais não tem access token.")

    return Credentials(
        access_token=token,
        subscription_type=str(block.get("subscriptionType") or ""),
        rate_limit_tier=str(block.get("rateLimitTier") or ""),
        expires_at=_expiry(block.get("expiresAt")),
    )
