"""Account capability implementation backed by the local account registry."""

from __future__ import annotations

from telegram_app.capabilities.base import CapabilityResult
from telegram_app.capabilities.mtproto.registry import AccountRegistry


class AccountCapabilityImpl:
    """Expose file-backed Telegram account metadata to the runtime."""

    def __init__(self, registry: AccountRegistry) -> None:
        self._registry = registry

    def list_accounts(self) -> CapabilityResult:
        accounts = [account.to_dict() for account in self._registry.list_accounts()]
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
            data={"account": account.to_dict(), "source": "mtproto_registry"},
            audit={"implementation": "mtproto_account_capability", "registry_path": str(self._registry.path)},
        )
