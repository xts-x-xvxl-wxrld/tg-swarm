"""Account capability implementation backed by the local account registry."""

from __future__ import annotations

from telegram_app.capabilities.base import CapabilityResult
from telegram_app.capabilities.mtproto.registry import AccountRegistry


class AccountCapabilityImpl:
    """Expose file-backed Telegram account metadata to the runtime."""

    def __init__(self, registry: AccountRegistry) -> None:
        self._registry = registry

    def list_accounts(self) -> CapabilityResult:
        accounts = [self._serialize_account(account.account_id, account.to_dict()) for account in self._registry.list_accounts()]
        return CapabilityResult(
            success=True,
            data={"accounts": accounts, "source": "mtproto_registry"},
            audit={"implementation": "mtproto_account_capability", "registry_path": str(self._registry.path)},
        )

    def get_account(self, account_id: str) -> CapabilityResult:
        account = self._registry.get_account(account_id)
        if account is None:
            return CapabilityResult(
                success=False,
                data={"account_id": account_id, "source": "mtproto_registry"},
                audit={"implementation": "mtproto_account_capability", "registry_path": str(self._registry.path)},
                error=f"Unknown Telegram account: {account_id}",
            )

        return CapabilityResult(
            success=True,
            data={"account": self._serialize_account(account.account_id, account.to_dict()), "source": "mtproto_registry"},
            audit={"implementation": "mtproto_account_capability", "registry_path": str(self._registry.path)},
        )

    def _serialize_account(self, account_id: str, payload: dict[str, object]) -> dict[str, object]:
        enriched = dict(payload)
        warmup = self._registry.describe_warmup(account_id)
        if warmup:
            enriched.update(warmup)
        return enriched
