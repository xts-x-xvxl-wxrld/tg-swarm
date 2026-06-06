"""Activation and invalidation logic for prepared execution state."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from uuid import uuid4

from telegram_app.live_execution import LiveActionStatus, LiveActionType, LiveExecutionManager
from telegram_app.models import SessionRecord, WorkItemStatus, WorkflowArtifact, WorkflowArtifactKind
from telegram_app.prepared_execution.manager import PreparedExecutionManager
from telegram_app.prepared_execution.models import (
    PreparedExecutionBatch,
    PreparedExecutionBatchStatus,
    PreparedExecutionItem,
    PreparedExecutionItemStatus,
)
from telegram_app.sessions import SessionManager
from telegram_app.work_items import WorkItemManager

ACCOUNT_PLANNING_WORK_TYPE = "account_planning"


@dataclass(slots=True)
class PreparedExecutionInvalidationResult:
    """Normalized result of invalidating stale prepared execution state."""

    superseded_batch_ids: list[str] = field(default_factory=list)
    superseded_item_ids: list[str] = field(default_factory=list)
    cancelled_action_ids: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        """Return whether invalidation mutated any durable runtime state."""
        return bool(
            self.superseded_batch_ids
            or self.superseded_item_ids
            or self.cancelled_action_ids
        )


@dataclass(slots=True)
class PlanActivationResult:
    """Structured outcome of one explicit account-plan activation request."""

    status: str
    message: str
    batch: PreparedExecutionBatch | None = None
    items: list[PreparedExecutionItem] = field(default_factory=list)
    queued_count: int = 0
    held_count: int = 0
    blocked_count: int = 0
    invalidation: PreparedExecutionInvalidationResult = field(default_factory=PreparedExecutionInvalidationResult)


class PreparedExecutionService:
    """Bridge approved account plans into campaign-owned prepared execution state."""

    def __init__(
        self,
        prepared_execution_manager: PreparedExecutionManager,
        live_execution_manager: LiveExecutionManager,
        *,
        session_manager: SessionManager | None = None,
        work_item_manager: WorkItemManager | None = None,
    ) -> None:
        self._prepared_execution_manager = prepared_execution_manager
        self._live_execution_manager = live_execution_manager
        self._session_manager = session_manager
        self._work_item_manager = work_item_manager

    def activate_latest_plan(
        self,
        session: SessionRecord,
        *,
        queue_immediately: bool = True,
    ) -> PlanActivationResult:
        """Materialize campaign-owned prepared execution from the latest approved plan."""
        if not session.campaign_id:
            return PlanActivationResult(
                status="unavailable",
                message="Execution activation is not available until this session is attached to a campaign.",
            )
        if self._session_manager is None:
            return PlanActivationResult(
                status="unavailable",
                message="Execution activation is not available in this runtime configuration yet.",
            )

        latest_plan = self._session_manager.get_latest_artifact_of_kind(
            session,
            WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
        )
        if latest_plan is None:
            return PlanActivationResult(
                status="missing_plan",
                message="I could not find an account assignment plan to activate yet.",
            )

        if not self._latest_plan_is_approved(session, latest_plan):
            return PlanActivationResult(
                status="approval_required",
                message="The latest account assignment plan is not approved yet. Say `approve` first, or tell me what to change.",
            )

        plan_fingerprint = self._artifact_fingerprint(latest_plan)
        invalidation = self.invalidate_stale_prepared_state(
            session,
            current_plan_fingerprint=plan_fingerprint,
        )
        existing_batch = self._find_existing_current_batch(session.campaign_id, plan_fingerprint)
        if existing_batch is not None:
            existing_items = self._prepared_execution_manager.list_items_for_campaign(
                session.campaign_id,
                batch_id=existing_batch.batch_id,
            )
            queued_count, held_count, blocked_count = self._item_status_counts(existing_items)
            message = self._build_activation_message(
                existing_batch,
                queued_count=queued_count,
                held_count=held_count,
                blocked_count=blocked_count,
                invalidation=invalidation,
                already_active=True,
            )
            return PlanActivationResult(
                status="already_active",
                message=message,
                batch=existing_batch,
                items=existing_items,
                queued_count=queued_count,
                held_count=held_count,
                blocked_count=blocked_count,
                invalidation=invalidation,
            )

        strategy_artifact = self._session_manager.get_latest_artifact_of_kind(
            session,
            WorkflowArtifactKind.STRATEGY_PLAYBOOK,
        )
        batch = PreparedExecutionBatch(
            batch_id=str(uuid4()),
            campaign_id=session.campaign_id,
            source_plan_artifact_id=latest_plan.artifact_id,
            source_plan_updated_at=latest_plan.updated_at,
            source_plan_fingerprint=plan_fingerprint,
            source_strategy_artifact_id=(
                strategy_artifact.artifact_id if strategy_artifact is not None else ""
            ),
            activated_by_operator_id=session.operator_id,
        )
        items = self._materialize_items(
            session,
            latest_plan,
            batch,
            queue_immediately=queue_immediately,
        )
        queued_count, held_count, blocked_count = self._item_status_counts(items)
        batch.queued_action_ids = [
            item.live_action_id
            for item in items
            if item.live_action_id
        ]
        batch.status = self._derive_batch_status(items)
        batch.summary = self._build_batch_summary(queued_count, held_count, blocked_count)
        self._prepared_execution_manager.save_batch(batch)
        self._prepared_execution_manager.save_items(session.campaign_id, items)
        message = self._build_activation_message(
            batch,
            queued_count=queued_count,
            held_count=held_count,
            blocked_count=blocked_count,
            invalidation=invalidation,
        )
        return PlanActivationResult(
            status="activated",
            message=message,
            batch=batch,
            items=items,
            queued_count=queued_count,
            held_count=held_count,
            blocked_count=blocked_count,
            invalidation=invalidation,
        )

    def invalidate_stale_prepared_state(
        self,
        session: SessionRecord,
        *,
        current_plan_fingerprint: str | None = None,
    ) -> PreparedExecutionInvalidationResult:
        """Supersede prepared state that no longer matches the latest saved plan."""
        result = PreparedExecutionInvalidationResult()
        if not session.campaign_id or self._session_manager is None:
            return result

        latest_plan = self._session_manager.get_latest_artifact_of_kind(
            session,
            WorkflowArtifactKind.ACCOUNT_ASSIGNMENT_PLAN,
        )
        if latest_plan is None:
            return result
        current_fingerprint = current_plan_fingerprint or self._artifact_fingerprint(latest_plan)

        for batch in self._prepared_execution_manager.list_batches_for_campaign(session.campaign_id):
            if not batch.is_active() or batch.source_plan_fingerprint == current_fingerprint:
                continue
            batch.status = PreparedExecutionBatchStatus.SUPERSEDED
            self._prepared_execution_manager.save_batch(batch)
            result.superseded_batch_ids.append(batch.batch_id)

            items = self._prepared_execution_manager.list_items_for_campaign(
                session.campaign_id,
                batch_id=batch.batch_id,
            )
            for item in items:
                if item.status is PreparedExecutionItemStatus.PREPARED:
                    item.status = PreparedExecutionItemStatus.SUPERSEDED
                    item.invalidated_reason = "Superseded by a newer account-plan revision."
                    self._prepared_execution_manager.save_item(item)
                    result.superseded_item_ids.append(item.prepared_item_id)
                    continue
                if item.live_action_id and item.status is PreparedExecutionItemStatus.QUEUED:
                    cancelled_action = self._live_execution_manager.cancel_action_if_pending(
                        session.campaign_id,
                        item.live_action_id,
                        reason="Superseded by a newer account-plan revision.",
                    )
                    if cancelled_action is not None:
                        item.status = PreparedExecutionItemStatus.CANCELLED
                        item.invalidated_reason = "Superseded by a newer account-plan revision."
                        item.result_summary = "Cancelled before execution because a newer approved plan replaced it."
                        self._prepared_execution_manager.save_item(item)
                        result.superseded_item_ids.append(item.prepared_item_id)
                        result.cancelled_action_ids.append(cancelled_action.action_id)
        return result

    def invalidate_stale_prepared_state_for_campaign(
        self,
        campaign_id: str,
        *,
        current_plan_fingerprint: str | None = None,
    ) -> PreparedExecutionInvalidationResult:
        """Invalidate stale prepared state using the latest session attached to a campaign."""
        result = PreparedExecutionInvalidationResult()
        if not campaign_id or self._session_manager is None:
            return result

        session = self._session_manager.get_latest_session_for_campaign(campaign_id)
        if session is None:
            return result
        return self.invalidate_stale_prepared_state(
            session,
            current_plan_fingerprint=current_plan_fingerprint,
        )

    def _find_existing_current_batch(
        self,
        campaign_id: str,
        plan_fingerprint: str,
    ) -> PreparedExecutionBatch | None:
        batch = self._prepared_execution_manager.find_latest_batch_by_fingerprint(
            campaign_id,
            plan_fingerprint,
        )
        if batch is None or not batch.is_active():
            return None
        return batch

    def _materialize_items(
        self,
        session: SessionRecord,
        plan_artifact: WorkflowArtifact,
        batch: PreparedExecutionBatch,
        *,
        queue_immediately: bool,
    ) -> list[PreparedExecutionItem]:
        assignments = plan_artifact.data.get("assignments", [])
        community_lookup = self._build_community_lookup(session)
        items: list[PreparedExecutionItem] = []

        for assignment_index, assignment in enumerate(assignments):
            if not isinstance(assignment, dict):
                continue
            assigned_account = str(assignment.get("assigned_account", "")).strip()
            community_name = str(assignment.get("community_name", "")).strip()
            community_handle = str(assignment.get("community_handle", "")).strip()
            scheduled_posts = assignment.get("scheduled_posts", [])
            if not isinstance(scheduled_posts, list):
                continue
            resolved_chat_id, resolved_community_id = self._resolve_assignment_target(
                community_name,
                community_handle,
                community_lookup,
            )

            for post_index, scheduled_post in enumerate(scheduled_posts):
                if not isinstance(scheduled_post, dict):
                    continue
                draft_text = str(scheduled_post.get("message_text", ""))
                day_offset = max(int(scheduled_post.get("day_offset", 0) or 0), 0)
                item = PreparedExecutionItem(
                    prepared_item_id=str(uuid4()),
                    batch_id=batch.batch_id,
                    campaign_id=batch.campaign_id,
                    action_type=LiveActionType.SEND_GROUP_MESSAGE,
                    account_id=assigned_account,
                    community_ref=community_handle or community_name,
                    chat_id=resolved_chat_id,
                    community_id=resolved_community_id,
                    source_assignment_index=assignment_index,
                    source_post_index=post_index,
                    day_offset=day_offset,
                    time_window=str(scheduled_post.get("time_window", "")).strip(),
                    draft_text=draft_text,
                    approval_context={
                        "approved": True,
                        "approval_mode": "operator",
                        "approval_source": "prepared_execution_activation",
                        "approval_reason": "approved_account_plan_activation",
                        "campaign_id": batch.campaign_id,
                        "approved_by": session.operator_id,
                        "approved_at": batch.activated_at.isoformat(),
                        "source_plan_artifact_id": plan_artifact.artifact_id,
                    },
                )
                item.status, item.result_summary = self._initial_item_state(
                    item,
                    queue_immediately=queue_immediately,
                )
                if item.status is PreparedExecutionItemStatus.QUEUED:
                    live_action = self._live_execution_manager.enqueue(
                        batch.campaign_id,
                        item.account_id,
                        action_type=item.action_type,
                        payload={
                            "chat_id": item.chat_id,
                            "community_id": item.community_id or item.community_ref,
                            "text": item.draft_text,
                            "approval_context": item.approval_context,
                        },
                        idempotency_key=f"prepared:{item.prepared_item_id}",
                        source_batch_id=batch.batch_id,
                        source_prepared_item_id=item.prepared_item_id,
                        source_plan_artifact_id=batch.source_plan_artifact_id,
                    )
                    item.live_action_id = live_action.action_id
                items.append(item)
        return items

    def _initial_item_state(
        self,
        item: PreparedExecutionItem,
        *,
        queue_immediately: bool,
    ) -> tuple[PreparedExecutionItemStatus, str]:
        if not item.account_id:
            return (
                PreparedExecutionItemStatus.BLOCKED,
                "No assigned account was available for this prepared execution item.",
            )
        if not item.chat_id:
            return (
                PreparedExecutionItemStatus.BLOCKED,
                "No community target could be resolved for this prepared execution item.",
            )
        if not item.draft_text.strip():
            return (
                PreparedExecutionItemStatus.BLOCKED,
                "The approved plan did not include message text for this prepared execution item.",
            )
        if item.day_offset > 0 or not queue_immediately:
            return (
                PreparedExecutionItemStatus.PREPARED,
                "Prepared and held for a later execution window.",
            )
        return (
            PreparedExecutionItemStatus.QUEUED,
            "Queued for live execution.",
        )

    def _latest_plan_is_approved(
        self,
        session: SessionRecord,
        latest_plan: WorkflowArtifact,
    ) -> bool:
        if self._work_item_manager is not None and session.campaign_id:
            completed_items = [
                item
                for item in self._work_item_manager.list_for_campaign(session.campaign_id)
                if item.work_type == ACCOUNT_PLANNING_WORK_TYPE
                and item.status is WorkItemStatus.COMPLETED
            ]
            if completed_items:
                latest_completed_item = max(completed_items, key=lambda item: item.updated_at)
                return latest_completed_item.updated_at >= latest_plan.updated_at
        if self._session_manager is None:
            return False
        snapshot = self._session_manager.get_workflow_snapshot(session)
        return "approved in chat" in snapshot.summary.lower()

    def _build_community_lookup(self, session: SessionRecord) -> dict[str, tuple[str, str]]:
        lookup: dict[str, tuple[str, str]] = {}
        if self._session_manager is None:
            return lookup
        shortlist = self._session_manager.get_latest_artifact_of_kind(
            session,
            WorkflowArtifactKind.COMMUNITY_SHORTLIST,
        )
        if shortlist is None:
            return lookup
        communities = shortlist.data.get("communities", [])
        if not isinstance(communities, list):
            return lookup
        for community in communities:
            if not isinstance(community, dict):
                continue
            handle = str(community.get("handle", "")).strip()
            community_id = str(community.get("community_id", "")).strip()
            chat_id = handle or community_id
            if not chat_id:
                continue
            for raw_key in {
                str(community.get("name", "")).strip(),
                handle,
                community_id,
            }:
                normalized_key = raw_key.lower()
                if normalized_key:
                    lookup[normalized_key] = (chat_id, community_id or handle)
        return lookup

    def _resolve_assignment_target(
        self,
        community_name: str,
        community_handle: str,
        community_lookup: dict[str, tuple[str, str]],
    ) -> tuple[str, str]:
        if community_handle:
            return community_handle, community_handle
        for key in (community_name.lower(), community_handle.lower()):
            if key and key in community_lookup:
                return community_lookup[key]
        return "", ""

    def _artifact_fingerprint(self, artifact: WorkflowArtifact) -> str:
        normalized_payload = json.dumps(
            artifact.data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(normalized_payload.encode("utf-8")).hexdigest()

    def _item_status_counts(
        self,
        items: list[PreparedExecutionItem],
    ) -> tuple[int, int, int]:
        queued_count = len(
            [item for item in items if item.status is PreparedExecutionItemStatus.QUEUED]
        )
        held_count = len(
            [item for item in items if item.status is PreparedExecutionItemStatus.PREPARED]
        )
        blocked_count = len(
            [item for item in items if item.status is PreparedExecutionItemStatus.BLOCKED]
        )
        return queued_count, held_count, blocked_count

    def _derive_batch_status(
        self,
        items: list[PreparedExecutionItem],
    ) -> PreparedExecutionBatchStatus:
        queued_count, held_count, _blocked_count = self._item_status_counts(items)
        if queued_count and held_count:
            return PreparedExecutionBatchStatus.PARTIALLY_QUEUED
        if queued_count:
            return PreparedExecutionBatchStatus.QUEUED
        return PreparedExecutionBatchStatus.PREPARED

    def _build_batch_summary(
        self,
        queued_count: int,
        held_count: int,
        blocked_count: int,
    ) -> str:
        return (
            f"Prepared {queued_count + held_count + blocked_count} execution item(s): "
            f"{queued_count} queued now, {held_count} held for later, {blocked_count} blocked."
        )

    def _build_activation_message(
        self,
        batch: PreparedExecutionBatch,
        *,
        queued_count: int,
        held_count: int,
        blocked_count: int,
        invalidation: PreparedExecutionInvalidationResult,
        already_active: bool = False,
    ) -> str:
        action_verb = "already prepared" if already_active else "prepared"
        details = (
            f"The latest approved account plan is {action_verb} for execution. "
            f"I have {queued_count} item(s) queued now, {held_count} held for later, and {blocked_count} blocked item(s) that still need plan cleanup."
        )
        if not invalidation.changed:
            return details
        return (
            f"{details} I also invalidated {len(invalidation.superseded_batch_ids)} stale prepared batch(es) "
            f"and cancelled {len(invalidation.cancelled_action_ids)} queued action(s) from the older revision."
        )
