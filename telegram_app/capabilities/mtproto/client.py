"""Thread-backed sync wrapper around Telethon's async client API."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import inspect
import threading
from typing import Any, TypeVar

from telegram_app.capabilities.mtproto.session_manager import TelethonSessionManager

T = TypeVar("T")
ClientOperation = Callable[[Any], Awaitable[T] | T]


class TelethonClientWrapper:
    """Run async Telegram client calls behind a synchronous interface."""

    def __init__(
        self,
        *,
        api_id: int | None,
        api_hash: str,
        session_manager: TelethonSessionManager,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._api_id = api_id
        self._api_hash = api_hash.strip()
        self._session_manager = session_manager
        self._timeout_seconds = timeout_seconds
        self._clients: dict[str, Any] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_event_loop,
            name="telethon-client-wrapper",
            daemon=True,
        )
        self._thread.start()
        self._loop_ready.wait()

    def connect(self, account_id: str) -> Any:
        """Ensure an account client is connected and return it."""
        return self._submit(self._connect_async(account_id))

    def disconnect(self, account_id: str) -> None:
        """Disconnect one account client if it exists."""
        self._submit(self._disconnect_async(account_id))

    def run(self, account_id: str, operation: ClientOperation[T]) -> T:
        """Execute an operation against a connected account client."""
        return self._submit(self._run_async(account_id, operation))

    def request_login_code(self, account_id: str, phone: str) -> dict[str, Any]:
        """Ask Telegram to send a one-time login code to the phone number."""
        return self._submit(self._request_login_code_async(account_id, phone))

    def sign_in_with_code(
        self,
        account_id: str,
        phone: str,
        code: str,
        phone_code_hash: str,
    ) -> dict[str, Any]:
        """Complete sign-in with a code, surfacing 2FA requirements when needed."""
        return self._submit(self._sign_in_with_code_async(account_id, phone, code, phone_code_hash))

    def sign_in_with_password(self, account_id: str, password: str) -> dict[str, Any]:
        """Complete sign-in for accounts that require a Telegram 2FA password."""
        return self._submit(self._sign_in_with_password_async(account_id, password))

    def is_available(self) -> tuple[bool, str]:
        """Report whether the wrapper has enough configuration to talk to Telegram."""
        if self._api_id is None or not self._api_hash:
            return False, "Telethon backend is not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH."

        try:
            self._session_manager.build_client("__availability_probe__", self._api_id, self._api_hash)
        except ModuleNotFoundError:
            return False, "Telethon is not installed. Add the dependency before enabling the MTProto backend."
        except Exception:
            return True, ""

        return True, ""

    async def _connect_async(self, account_id: str) -> Any:
        available, error = self.is_available()
        if not available:
            raise RuntimeError(error)

        client = self._clients.get(account_id)
        if client is None:
            assert self._api_id is not None
            client = self._session_manager.build_client(account_id, self._api_id, self._api_hash)
            self._clients[account_id] = client

        if hasattr(client, "is_connected") and client.is_connected():
            return client

        await client.connect()
        return client

    async def _disconnect_async(self, account_id: str) -> None:
        client = self._clients.get(account_id)
        if client is None:
            return
        await client.disconnect()
        self._clients.pop(account_id, None)

    async def _run_async(self, account_id: str, operation: ClientOperation[T]) -> T:
        client = await self._connect_async(account_id)
        result = operation(client)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _request_login_code_async(self, account_id: str, phone: str) -> dict[str, Any]:
        client = await self._connect_async(account_id)
        sent_code = await client.send_code_request(phone)
        return {
            "phone_code_hash": getattr(sent_code, "phone_code_hash", ""),
        }

    async def _sign_in_with_code_async(
        self,
        account_id: str,
        phone: str,
        code: str,
        phone_code_hash: str,
    ) -> dict[str, Any]:
        client = await self._connect_async(account_id)
        try:
            user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except Exception as exc:
            if exc.__class__.__name__ == "SessionPasswordNeededError":
                return {"success": False, "password_required": True, "error": ""}
            raise

        return {"success": True, "password_required": False, "user": self._serialize_user(user)}

    async def _sign_in_with_password_async(self, account_id: str, password: str) -> dict[str, Any]:
        client = await self._connect_async(account_id)
        user = await client.sign_in(password=password)
        return {"success": True, "password_required": False, "user": self._serialize_user(user)}

    def forget_account(self, account_id: str) -> None:
        """Disconnect and delete local state for an account."""
        self.disconnect(account_id)
        self._session_manager.delete_session_file(account_id)

    def _submit(self, coroutine: Awaitable[T]) -> T:
        if self._loop is None:
            raise RuntimeError("Telethon event loop was not initialized.")

        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=self._timeout_seconds)

    def _run_event_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._loop_ready.set()
        loop.run_forever()

    def _serialize_user(self, user: Any) -> dict[str, Any]:
        return {
            "id": getattr(user, "id", None),
            "username": getattr(user, "username", "") or "",
            "first_name": getattr(user, "first_name", "") or "",
            "last_name": getattr(user, "last_name", "") or "",
            "phone": getattr(user, "phone", "") or "",
        }
