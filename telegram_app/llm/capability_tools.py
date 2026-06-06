"""Shared Anthropic tool-use support for Telegram capability reads."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from telegram_app.capabilities import (
    AccountCapability,
    CommunityCapability,
    MembershipCapability,
    MessagingCapability,
)

MAX_TOOL_ROUNDS = 6
MAX_TOOL_RESULT_LIST_ITEMS = 8
MAX_TOOL_RESULT_TEXT_LENGTH = 400


@dataclass(slots=True)
class ToolEnabledCompletionResult:
    """Normalized Anthropic completion result with Telegram tool metadata."""

    final_output: str
    tool_call_count: int = 0
    tool_names: list[str] = field(default_factory=list)


class TelegramCapabilityToolbox:
    """Expose bounded Telegram capability reads as Anthropic tools."""

    def __init__(
        self,
        *,
        account_capability: AccountCapability | None = None,
        community_capability: CommunityCapability | None = None,
        membership_capability: MembershipCapability | None = None,
        messaging_capability: MessagingCapability | None = None,
    ) -> None:
        self._account_capability = account_capability
        self._community_capability = community_capability
        self._membership_capability = membership_capability
        self._messaging_capability = messaging_capability

    def build_tools(self) -> list[dict[str, Any]]:
        """Return the Anthropic tool schemas available in this runtime."""
        tools: list[dict[str, Any]] = []

        if self._account_capability is not None:
            tools.extend(
                [
                    {
                        "name": "telegram_list_accounts",
                        "description": "List managed Telegram accounts and their readiness metadata.",
                        "input_schema": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                    {
                        "name": "telegram_get_account",
                        "description": "Get details for one managed Telegram account by account_id.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "account_id": {"type": "string"},
                            },
                            "required": ["account_id"],
                            "additionalProperties": False,
                        },
                    },
                ]
            )

        if self._community_capability is not None:
            tools.extend(
                [
                    {
                        "name": "telegram_search_communities",
                        "description": "Search Telegram communities by query using exact or harvest search mode.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "mode": {"type": "string", "enum": ["exact", "harvest"]},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                            },
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    },
                    {
                        "name": "telegram_get_community_profile",
                        "description": "Get a live Telegram community profile by handle, username, or community id.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "community_id": {"type": "string"},
                            },
                            "required": ["community_id"],
                            "additionalProperties": False,
                        },
                    },
                ]
            )

        if self._membership_capability is not None:
            tools.append(
                {
                    "name": "telegram_get_membership",
                    "description": "Inspect whether an account is already a member of a Telegram community.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "account_id": {"type": "string"},
                            "community_id": {"type": "string"},
                        },
                        "required": ["account_id", "community_id"],
                        "additionalProperties": False,
                    },
                }
            )

        if self._messaging_capability is not None:
            tools.extend(
                [
                    {
                        "name": "telegram_read_messages",
                        "description": "Read recent messages from a Telegram chat or community.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "chat_id": {"type": "string"},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                            },
                            "required": ["chat_id"],
                            "additionalProperties": False,
                        },
                    },
                    {
                        "name": "telegram_get_dialog_history",
                        "description": "Read bounded dialog history for one managed account and peer.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "account_id": {"type": "string"},
                                "peer_id": {"type": "string"},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                            },
                            "required": ["account_id", "peer_id"],
                            "additionalProperties": False,
                        },
                    },
                    {
                        "name": "telegram_list_recent_dialogs",
                        "description": "List recent dialogs for one managed Telegram account.",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "account_id": {"type": "string"},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                            },
                            "required": ["account_id"],
                            "additionalProperties": False,
                        },
                    },
                ]
            )

        return tools

    def run_completion(
        self,
        *,
        client: Any,
        model: str,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ToolEnabledCompletionResult:
        """Run one Anthropic completion, looping through Telegram tool calls when needed."""
        conversation_messages = list(messages)
        tools = self.build_tools()
        response = self._create_message(
            client=client,
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=conversation_messages,
            tools=tools,
        )
        tool_names: list[str] = []

        for _ in range(MAX_TOOL_ROUNDS):
            tool_uses = _extract_tool_use_blocks(response.content)
            if not tool_uses:
                break

            conversation_messages.append(
                {
                    "role": "assistant",
                    "content": _serialize_assistant_content(response.content),
                }
            )
            tool_result_blocks: list[dict[str, Any]] = []
            for tool_use in tool_uses:
                tool_name = str(tool_use.get("name", "")).strip()
                tool_input = tool_use.get("input", {})
                tool_names.append(tool_name)
                result = self.execute_tool(tool_name, tool_input if isinstance(tool_input, dict) else {})
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": str(tool_use.get("id", "")),
                        "content": json.dumps(result, ensure_ascii=True, sort_keys=True),
                        "is_error": not bool(result.get("success")),
                    }
                )
            conversation_messages.append({"role": "user", "content": tool_result_blocks})
            response = self._create_message(
                client=client,
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=conversation_messages,
                tools=tools,
            )

        return ToolEnabledCompletionResult(
            final_output=_extract_text_output(response.content),
            tool_call_count=len(tool_names),
            tool_names=tool_names,
        )

    def execute_tool(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute one named Telegram capability tool and normalize the result."""
        if name == "telegram_list_accounts" and self._account_capability is not None:
            return self._normalize_result(self._account_capability.list_accounts())
        if name == "telegram_get_account" and self._account_capability is not None:
            return self._normalize_result(self._account_capability.get_account(str(payload.get("account_id", "")).strip()))
        if name == "telegram_search_communities" and self._community_capability is not None:
            query = str(payload.get("query", "")).strip()
            mode = str(payload.get("mode", "exact") or "exact").strip() or "exact"
            limit = _bounded_int(payload.get("limit"), default=10, minimum=1, maximum=25)
            return self._normalize_result(self._community_capability.search(query, mode=mode, limit=limit))
        if name == "telegram_get_community_profile" and self._community_capability is not None:
            community_id = str(payload.get("community_id", "")).strip()
            return self._normalize_result(self._community_capability.get_profile(community_id))
        if name == "telegram_get_membership" and self._membership_capability is not None:
            account_id = str(payload.get("account_id", "")).strip()
            community_id = str(payload.get("community_id", "")).strip()
            return self._normalize_result(self._membership_capability.get_membership(account_id, community_id))
        if name == "telegram_read_messages" and self._messaging_capability is not None:
            chat_id = str(payload.get("chat_id", "")).strip()
            limit = _bounded_int(payload.get("limit"), default=10, minimum=1, maximum=25)
            return self._normalize_result(self._messaging_capability.read_messages(chat_id, limit=limit))
        if name == "telegram_get_dialog_history" and self._messaging_capability is not None:
            account_id = str(payload.get("account_id", "")).strip()
            peer_id = str(payload.get("peer_id", "")).strip()
            limit = _bounded_int(payload.get("limit"), default=10, minimum=1, maximum=25)
            return self._normalize_result(self._messaging_capability.get_dialog_history(account_id, peer_id, limit=limit))
        if name == "telegram_list_recent_dialogs" and self._messaging_capability is not None:
            account_id = str(payload.get("account_id", "")).strip()
            limit = _bounded_int(payload.get("limit"), default=10, minimum=1, maximum=25)
            return self._normalize_result(self._messaging_capability.list_recent_dialogs(account_id, limit=limit))

        return {
            "success": False,
            "error": f"Unsupported Telegram capability tool: {name}",
            "data": {},
        }

    def _create_message(
        self,
        *,
        client: Any,
        model: str,
        max_tokens: int,
        system: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            request["tools"] = tools
        return client.messages.create(**request)

    def _normalize_result(self, result: Any) -> dict[str, Any]:
        success = bool(getattr(result, "success", False))
        data = getattr(result, "data", {})
        audit = getattr(result, "audit", {})
        error = str(getattr(result, "error", "") or "").strip()
        payload = {
            "success": success,
            "data": _sanitize_for_prompt(data),
        }
        compact_audit = _sanitize_for_prompt(audit)
        if compact_audit not in ("", [], {}, None):
            payload["audit"] = compact_audit
        if error:
            payload["error"] = error
        return payload


def _extract_tool_use_blocks(content: Any) -> list[dict[str, Any]]:
    tool_uses: list[dict[str, Any]] = []
    if not isinstance(content, list):
        return tool_uses
    for block in content:
        block_type = _block_value(block, "type")
        if block_type != "tool_use":
            continue
        tool_uses.append(
            {
                "id": _block_value(block, "id"),
                "name": _block_value(block, "name"),
                "input": _block_value(block, "input") or {},
            }
        )
    return tool_uses


def _serialize_assistant_content(content: Any) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    if not isinstance(content, list):
        return serialized
    for block in content:
        block_type = _block_value(block, "type")
        if block_type == "tool_use":
            serialized.append(
                {
                    "type": "tool_use",
                    "id": str(_block_value(block, "id") or ""),
                    "name": str(_block_value(block, "name") or ""),
                    "input": _block_value(block, "input") or {},
                }
            )
            continue
        text = str(_block_value(block, "text") or "").strip()
        if text:
            serialized.append({"type": "text", "text": text})
    return serialized


def _extract_text_output(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    text_blocks: list[str] = []
    for block in content:
        text = str(_block_value(block, "text") or "").strip()
        if text:
            text_blocks.append(text)
    return "".join(text_blocks).strip()


def _block_value(block: Any, key: str) -> Any:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def _sanitize_for_prompt(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            compact_item = _sanitize_for_prompt(item)
            if compact_item in ("", [], {}, None):
                continue
            sanitized[str(key)] = compact_item
        return sanitized

    if isinstance(value, list):
        sanitized_items = [
            _sanitize_for_prompt(item)
            for item in value[:MAX_TOOL_RESULT_LIST_ITEMS]
        ]
        return [item for item in sanitized_items if item not in ("", [], {}, None)]

    if isinstance(value, str):
        compact = " ".join(value.split())
        if len(compact) > MAX_TOOL_RESULT_TEXT_LENGTH:
            return compact[: MAX_TOOL_RESULT_TEXT_LENGTH - 3] + "..."
        return compact

    return value


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))
