"""Telethon-backed Telegram capability implementations."""

from .audit_logger import JsonlAuditLogger
from .auth_gateway import TelethonAuthGateway
from .client import TelethonClientWrapper
from .impl_accounts import AccountCapabilityImpl
from .impl_communities import CommunityCapabilityImpl
from .impl_membership import MembershipCapabilityImpl
from .impl_messaging import MessagingCapabilityImpl
from .registry import AccountRecord, AccountRegistry
from .session_manager import TelethonSessionManager

__all__ = [
    "AccountCapabilityImpl",
    "AccountRecord",
    "AccountRegistry",
    "CommunityCapabilityImpl",
    "JsonlAuditLogger",
    "MembershipCapabilityImpl",
    "MessagingCapabilityImpl",
    "TelethonAuthGateway",
    "TelethonClientWrapper",
    "TelethonSessionManager",
]
