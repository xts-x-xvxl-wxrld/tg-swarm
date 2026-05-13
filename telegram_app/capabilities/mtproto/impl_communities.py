"""Community capability implementation backed by Telethon."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from telegram_app.capabilities.base import CapabilityResult
from telegram_app.capabilities.mtproto.client import TelethonClientWrapper
from telegram_app.capabilities.mtproto.registry import AccountRegistry

SPARSE_HARVEST_RESULT_THRESHOLD = 3


def _isoformat_if_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return ""


def _community_type(entity: Any) -> str:
    if getattr(entity, "broadcast", False):
        return "channel"
    if getattr(entity, "megagroup", False):
        return "supergroup"
    return "group"


def _normalize_search_result(entity: Any) -> dict[str, Any]:
    return {
        "community_id": str(getattr(entity, "id", "")),
        "name": getattr(entity, "title", "") or getattr(entity, "username", ""),
        "username": getattr(entity, "username", "") or "",
        "type": _community_type(entity),
        "member_count": getattr(entity, "participants_count", None),
        "verified": bool(getattr(entity, "verified", False)),
        "scam": bool(getattr(entity, "scam", False)),
        "restricted": bool(getattr(entity, "restricted", False)),
    }


class CommunityCapabilityImpl:
    """Read Telegram community metadata through a shared MTProto wrapper."""

    def __init__(self, registry: AccountRegistry, client_wrapper: TelethonClientWrapper) -> None:
        self._registry = registry
        self._client_wrapper = client_wrapper

    def search(self, query: str, *, mode: str = "exact", limit: int = 10) -> CapabilityResult:
        account = self._registry.resolve_default_read_account()
        if account is None:
            return self._missing_account_result("search", query=query, mode=mode, limit=limit)

        available, error = self._client_wrapper.is_available()
        if not available:
            return self._unavailable_result(
                "search",
                error,
                query=query,
                mode=mode,
                limit=limit,
                account_id=account.account_id,
            )

        try:
            search_payload = self._client_wrapper.run(
                account.account_id,
                lambda client: self._search_async(client, query, mode=mode, limit=limit),
            )
        except Exception as exc:
            return self._unavailable_result(
                "search",
                f"Telegram community search failed: {exc}",
                query=query,
                mode=mode,
                limit=limit,
                account_id=account.account_id,
            )

        return CapabilityResult(
            success=True,
            data={
                "query": query,
                "mode": mode,
                "limit": limit,
                "results": search_payload["results"],
                "source": search_payload["source"],
                "fallback_used": search_payload.get("fallback_used", False),
            },
            audit={
                "implementation": "mtproto_community_capability",
                "account_id": account.account_id,
            },
        )

    def get_profile(self, community_id: str) -> CapabilityResult:
        account = self._registry.resolve_default_read_account()
        if account is None:
            return self._missing_account_result("get_profile", community_id=community_id)

        available, error = self._client_wrapper.is_available()
        if not available:
            return self._unavailable_result(
                "get_profile",
                error,
                community_id=community_id,
                account_id=account.account_id,
            )

        try:
            profile = self._client_wrapper.run(
                account.account_id,
                lambda client: self._get_profile_async(client, community_id),
            )
        except Exception as exc:
            return self._unavailable_result(
                "get_profile",
                f"Telegram community profiling failed: {exc}",
                community_id=community_id,
                account_id=account.account_id,
            )

        return CapabilityResult(
            success=True,
            data={"community": profile, "source": "telethon"},
            audit={
                "implementation": "mtproto_community_capability",
                "account_id": account.account_id,
            },
        )

    async def _search_async(self, client: Any, query: str, *, mode: str, limit: int) -> dict[str, Any]:
        if query.strip().startswith("@"):
            entity = await client.get_entity(query.strip())
            return {
                "results": [self._annotate_search_result(_normalize_search_result(entity), source="telethon_get_entity")],
                "source": "telethon_get_entity",
                "fallback_used": False,
            }

        if mode not in {"exact", "harvest"}:
            raise ValueError(f"Unsupported community search mode: {mode}")

        contacts_results = await self._search_contacts_async(client, query, limit=limit)
        if mode != "harvest" or len(contacts_results) >= SPARSE_HARVEST_RESULT_THRESHOLD:
            return {
                "results": contacts_results,
                "source": "telethon_contacts_search",
                "fallback_used": False,
            }

        global_results = await self._search_global_async(client, query, limit=limit)
        merged_results = self._merge_search_results(contacts_results, global_results)
        if not global_results:
            return {
                "results": contacts_results,
                "source": "telethon_contacts_search",
                "fallback_used": False,
            }
        return {
            "results": merged_results,
            "source": "telethon_hybrid_harvest",
            "fallback_used": True,
        }

    async def _search_contacts_async(self, client: Any, query: str, *, limit: int) -> list[dict[str, Any]]:
        from telethon.tl.functions.contacts import SearchRequest

        response = await client(SearchRequest(q=query, limit=limit))
        chats: Iterable[Any] = getattr(response, "chats", [])
        return [
            self._annotate_search_result(_normalize_search_result(chat), source="telethon_contacts_search")
            for chat in chats
        ]

    async def _search_global_async(self, client: Any, query: str, *, limit: int) -> list[dict[str, Any]]:
        from telethon.tl.functions.messages import SearchGlobalRequest
        from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty

        response = await client(
            SearchGlobalRequest(
                q=query,
                filter=InputMessagesFilterEmpty(),
                min_date=None,
                max_date=None,
                offset_rate=0,
                offset_peer=InputPeerEmpty(),
                offset_id=0,
                limit=limit,
                users_only=False,
            )
        )
        chats: Iterable[Any] = getattr(response, "chats", [])
        return [
            self._annotate_search_result(_normalize_search_result(chat), source="telethon_messages_search_global")
            for chat in chats
        ]

    def _annotate_search_result(self, result: dict[str, Any], *, source: str) -> dict[str, Any]:
        annotated = dict(result)
        annotated["search_source"] = source
        return annotated

    def _merge_search_results(
        self,
        contacts_results: list[dict[str, Any]],
        global_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged_results = list(contacts_results)
        seen_keys = {self._result_identity(result) for result in contacts_results}
        for result in global_results:
            result_key = self._result_identity(result)
            if result_key in seen_keys:
                continue
            merged_results.append(result)
            seen_keys.add(result_key)
        return merged_results

    def _result_identity(self, result: dict[str, Any]) -> tuple[str, str]:
        community_id = str(result.get("community_id", "")).strip()
        username = str(result.get("username", "")).strip().lower()
        return community_id, username

    async def _get_profile_async(self, client: Any, community_id: str) -> dict[str, Any]:
        entity = await client.get_entity(community_id)
        profile = _normalize_search_result(entity)
        profile["description"] = ""
        profile["linked_chat_id"] = None
        profile["slowmode_seconds"] = None
        profile["created_at"] = _isoformat_if_datetime(getattr(entity, "date", None))

        if getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False):
            from telethon.tl.functions.channels import GetFullChannelRequest

            full_response = await client(GetFullChannelRequest(channel=entity))
            full_chat = getattr(full_response, "full_chat", None)
            if full_chat is not None:
                profile["description"] = getattr(full_chat, "about", "") or ""
                profile["member_count"] = getattr(full_chat, "participants_count", profile["member_count"])
                profile["linked_chat_id"] = getattr(full_chat, "linked_chat_id", None)
                profile["slowmode_seconds"] = getattr(full_chat, "slowmode_seconds", None)

        return profile

    def _missing_account_result(self, action: str, **data: Any) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={**data, "source": "telethon"},
            audit={"implementation": "mtproto_community_capability", "action": action},
            error="No Telegram account is configured for live community reads.",
        )

    def _unavailable_result(self, action: str, error: str, **data: Any) -> CapabilityResult:
        return CapabilityResult(
            success=False,
            data={**data, "source": "telethon"},
            audit={"implementation": "mtproto_community_capability", "action": action},
            error=error,
        )
