"""Discovery specialist agent for Telegram community shortlist generation."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

import anthropic

from telegram_app.approvals import ApprovalManager
from telegram_app.campaign_memory import CampaignMemoryManager
from telegram_app.capabilities import CommunityCapability, MessagingCapability
from telegram_app.discovery import (
    parse_discovery_shortlist,
    persist_discovery_shortlist,
    strip_discovery_json_block,
)
from telegram_app.intake import get_campaign_brief_artifact
from telegram_app.monitoring import NullRuntimeEventLogger, RuntimeEventLogger, RuntimeTraceContext
from telegram_app.models import ApprovalRecord, SessionRecord, WorkflowArtifact, WorkflowArtifactKind
from telegram_app.orchestrator.context_builder import build_runtime_context
from telegram_app.sessions import SessionManager

logger = logging.getLogger(__name__)

# agents/discovery/agent.py -> agents/discovery/ -> agents/ -> tg-swarm/ (repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DISCOVERY_SEARCH_RESULT_KEYS = (
    "community_id",
    "name",
    "username",
    "type",
    "member_count",
    "verified",
    "restricted",
    "scam",
)
DISCOVERY_TOP_CANDIDATE_KEYS = (
    "community_id",
    "name",
    "username",
    "type",
    "member_count",
    "verified",
    "restricted",
    "scam",
    "matched_queries",
)
DISCOVERY_QUERY_BUDGET = 8
DISCOVERY_TOP_CANDIDATE_BUDGET = 6
DISCOVERY_EXACT_QUERY_RESULT_LIMIT = 10
DISCOVERY_HARVEST_QUERY_RESULT_LIMIT = 15
DISCOVERY_REFINEMENT_QUERY_BUDGET = 4
DISCOVERY_REFINEMENT_MIN_UNIQUE_CANDIDATES = 3
DISCOVERY_PRIMARY_CITY_HUB_COUNT = 2
DISCOVERY_PRIMARY_RELATED_VARIANT_COUNT = 2
VERIFICATION_STATE_LIVE_CONFIRMED = "live_confirmed"
VERIFICATION_STATE_SEARCH_CONFIRMED = "search_confirmed"
VERIFICATION_STATE_TRAINING_KNOWLEDGE_FALLBACK = "training_knowledge_fallback"
EXACT_MATCH_KINDS = frozenset({"exact_handle", "exact_name"})
APPROXIMATE_MATCH_KINDS = frozenset({"name_contains", "token_close"})
_MATCH_STOPWORDS = frozenset({"and", "by", "chat", "channel", "community", "for", "group", "of", "official", "telegram", "the"})
_GEOGRAPHY_CITY_HUBS = {
    "europe": ("Berlin", "London", "Paris", "Amsterdam", "Lisbon", "Stockholm"),
    "mena": ("Dubai", "Riyadh", "Cairo", "Doha", "Abu Dhabi"),
}


def _load_prompt(name: str) -> str:
    return (REPO_ROOT / "prompts" / name).read_text(encoding="utf-8")


def _resolve_model() -> str:
    model = os.getenv("DEFAULT_MODEL", "claude-sonnet-4-6").strip()
    if "/" in model:
        model = model.split("/", 1)[1]
    if not model.startswith("claude-"):
        model = "claude-sonnet-4-6"
    return model


class DiscoveryAgent:
    """Specialist agent for Telegram community discovery and shortlist generation."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        approval_manager: ApprovalManager | None = None,
        community_capability: CommunityCapability | None = None,
        messaging_capability: MessagingCapability | None = None,
        monitor: RuntimeEventLogger | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._approval_manager = approval_manager
        self._community_capability = community_capability
        self._messaging_capability = messaging_capability
        self._monitor = monitor or NullRuntimeEventLogger()
        self._memory_manager = CampaignMemoryManager()
        self._client = anthropic.Anthropic()

    def run(
        self,
        session: SessionRecord,
        operator_message: str,
        trace_context: RuntimeTraceContext | None = None,
    ) -> tuple[str, WorkflowArtifact | None, ApprovalRecord | None]:
        """Run one discovery turn. Returns (operator_text, artifact, approval)."""
        trace_context = (
            trace_context
            or RuntimeTraceContext(trace_id="", session_id=session.session_id, user_id=session.operator_id)
        ).with_session(session)
        system = [
            {"type": "text", "text": _load_prompt("discovery.md")},
            {"type": "text", "text": _load_prompt("shared_runtime.md")},
            {"type": "text", "text": build_runtime_context(session, pending_approval=None, discovery_mode=True)},
        ]
        specialist_memory = self._memory_manager.load_agent_prompt_memory(session, "discovery")
        if specialist_memory:
            system.append(
                {
                    "type": "text",
                    "text": "Discovery specialist working memory:\n"
                    + json.dumps(specialist_memory, ensure_ascii=True, sort_keys=True),
                }
            )
        user_content, brief_search_diagnostics = self._build_user_content(session, operator_message)
        messages = [{"role": "user", "content": user_content}]

        model = _resolve_model()
        logger.info("DiscoveryAgent calling Anthropic API model=%s", model)
        self._monitor.record_event(
            component="discovery_agent",
            event_type="llm_request",
            trace_context=trace_context,
            session=session,
            payload={
                "model": model,
                "prompt_assets": ["discovery.md", "shared_runtime.md"],
                "messages": messages,
            },
        )

        try:
            api_response = self._client.messages.create(
                model=model,
                max_tokens=4096,
                system=system,
                messages=messages,
            )
        except Exception as exc:
            self._monitor.record_event(
                component="discovery_agent",
                event_type="llm_failed",
                trace_context=trace_context,
                session=session,
                payload={"model": model, "error": str(exc), "error_type": type(exc).__name__},
            )
            raise

        final_output = "".join(
            block.text for block in api_response.content if hasattr(block, "text")
        ).strip()

        artifact: WorkflowArtifact | None = None
        approval: ApprovalRecord | None = None

        if self._session_manager is not None and self._approval_manager is not None:
            shortlist_payload = parse_discovery_shortlist(final_output)
            if shortlist_payload is not None:
                shortlist_payload, live_summary = self._enrich_shortlist(
                    shortlist_payload,
                    brief_search_diagnostics=brief_search_diagnostics,
                )
                artifact, approval = persist_discovery_shortlist(
                    session_manager=self._session_manager,
                    approval_manager=self._approval_manager,
                    session=session,
                    shortlist_payload=shortlist_payload,
                )
            else:
                live_summary = ""
        else:
            shortlist_payload = parse_discovery_shortlist(final_output)
            if shortlist_payload is not None:
                shortlist_payload, live_summary = self._enrich_shortlist(
                    shortlist_payload,
                    brief_search_diagnostics=brief_search_diagnostics,
                )
                summary = str(shortlist_payload.get("summary", "")).strip() or "Community shortlist ready."
                artifact = WorkflowArtifact(
                    artifact_id=str(uuid4()),
                    kind=WorkflowArtifactKind.COMMUNITY_SHORTLIST,
                    title="Community shortlist",
                    summary=summary,
                    data=shortlist_payload,
                )
            else:
                live_summary = ""

        operator_text = strip_discovery_json_block(final_output)
        if live_summary:
            operator_text = f"{operator_text}\n\nLive Telegram validation: {live_summary}"
        if artifact is not None:
            self._write_working_memory(session, artifact, operator_message, live_summary)
        self._monitor.record_event(
            component="discovery_agent",
            event_type="llm_response",
            trace_context=trace_context,
            session=session,
            approval=approval,
            payload={
                "model": model,
                "output_text": final_output,
                "operator_text": operator_text,
                "artifact_id": artifact.artifact_id if artifact is not None else "",
                "approval_id": approval.approval_id if approval is not None else "",
                "live_summary": live_summary,
            },
        )
        return operator_text, artifact, approval

    def _write_working_memory(
        self,
        session: SessionRecord,
        artifact: WorkflowArtifact,
        operator_message: str,
        live_summary: str,
    ) -> None:
        summary = str(artifact.data.get("summary", "")).strip() or artifact.summary
        communities = artifact.data.get("communities", [])
        lines = ["# Discovery Notes", ""]
        if summary:
            lines.extend(["## Current Shortlist", "", summary])
        if live_summary.strip():
            lines.extend(["", "## Live Validation", "", live_summary.strip()])
        if operator_message.strip():
            lines.extend(["", "## Latest Operator Context", "", operator_message.strip()])
        if isinstance(communities, list) and communities:
            lines.extend(["", "## Highest-Signal Communities", ""])
            for community in communities[:5]:
                if not isinstance(community, dict):
                    continue
                name = str(community.get("name") or community.get("handle") or "Community").strip()
                verification_state = str(community.get("verification_state", "")).strip()
                reason = str(community.get("reason", "")).strip()
                details = " | ".join(
                    value
                    for value in [
                        verification_state,
                        reason,
                    ]
                    if value
                )
                lines.append(f"- {name}: {details or 'Candidate captured in the latest shortlist.'}")
        lines.extend(
            [
                "",
                "## Next Discovery Move",
                "",
                "Revise this note when operator feedback changes the search criteria, validation depth, or shortlist coverage goals.",
            ]
        )
        self._memory_manager.write_agent_working_memory(session, "discovery", "\n".join(lines))

    def _build_user_content(
        self,
        session: SessionRecord,
        operator_message: str,
    ) -> tuple[str, dict[str, Any] | None]:
        capability_context, brief_search_diagnostics = self._build_capability_context(session)
        if not capability_context:
            return operator_message, brief_search_diagnostics
        return f"{operator_message}\n\n{capability_context}", brief_search_diagnostics

    def _build_capability_context(self, session: SessionRecord) -> tuple[str, dict[str, Any] | None]:
        lines = ["Capability context:"]
        query_specs = self._build_search_query_specs(session)
        brief_search_diagnostics: dict[str, Any] | None = None

        if self._community_capability is None or not query_specs:
            lines.append("- community_search_summary: unavailable")
        else:
            prompt_summary, brief_search_diagnostics = self._run_brief_searches(session, query_specs)
            lines.append(
                "- community_search_summary: "
                + json.dumps(prompt_summary, ensure_ascii=True, sort_keys=True)
            )

        if self._messaging_capability is None:
            lines.append("- messaging_reads: unavailable")
        else:
            lines.append("- messaging_reads: available for live sampling during shortlist enrichment")

        return "\n".join(lines), brief_search_diagnostics

    def _build_search_queries(self, session: SessionRecord) -> list[str]:
        return [spec["query"] for spec in self._build_search_query_specs(session)]

    def _build_search_inputs(self, session: SessionRecord) -> dict[str, str] | None:
        campaign_brief = get_campaign_brief_artifact(session)
        if campaign_brief is None:
            return None

        objective = self._normalize_query_text(campaign_brief.data.get("objective", ""))
        audience = self._normalize_query_text(campaign_brief.data.get("target_audience", ""))
        geography = self._normalize_query_text(campaign_brief.data.get("geography", ""))
        offer = self._normalize_query_text(campaign_brief.data.get("offer", ""))
        objective_focus = self._extract_objective_focus(objective)
        core_phrase = audience or objective_focus

        return {
            "objective": objective,
            "audience": audience,
            "geography": geography,
            "offer": offer,
            "objective_focus": objective_focus,
            "core_phrase": core_phrase,
        }

    def _build_search_query_specs(self, session: SessionRecord) -> list[dict[str, str]]:
        search_inputs = self._build_search_inputs(session)
        if search_inputs is None:
            return []

        geography = search_inputs["geography"]
        offer = search_inputs["offer"]
        objective_focus = search_inputs["objective_focus"]
        core_phrase = search_inputs["core_phrase"]

        specs: list[dict[str, str]] = []
        self._append_query_spec(specs, "core_with_geography", f"{core_phrase} {geography}")
        self._append_query_spec(specs, "core", core_phrase)

        for variant in self._build_related_phrase_variants(core_phrase, objective_focus)[:DISCOVERY_PRIMARY_RELATED_VARIANT_COUNT]:
            self._append_query_spec(specs, "related_with_geography", f"{variant} {geography}")
            self._append_query_spec(specs, "related", variant)

        for city_hub in self._city_hubs_for_geography(geography)[:DISCOVERY_PRIMARY_CITY_HUB_COUNT]:
            self._append_query_spec(specs, "city_hub", f"{city_hub} {core_phrase}")

        if objective_focus and objective_focus != core_phrase:
            self._append_query_spec(specs, "objective_with_geography", f"{objective_focus} {geography}")
            self._append_query_spec(specs, "objective", objective_focus)

        if offer:
            self._append_query_spec(specs, "offer", f"{core_phrase} {offer}")

        return specs[:DISCOVERY_QUERY_BUDGET]

    def _run_brief_searches(
        self,
        session: SessionRecord,
        query_specs: list[dict[str, str]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        query_diagnostics: list[dict[str, Any]] = []
        candidate_pool: dict[str, dict[str, Any]] = {}
        self._execute_harvest_queries(
            query_specs,
            candidate_pool=candidate_pool,
            query_diagnostics=query_diagnostics,
            search_pass="first_pass",
        )

        unique_candidates_before_refinement = len(candidate_pool)
        productive_query_families = self._productive_query_families(query_diagnostics)
        refinement_specs = self._build_refinement_query_specs(
            session,
            attempted_queries={spec["query"] for spec in query_specs},
            productive_query_families=productive_query_families,
        )
        refinement_triggered = (
            unique_candidates_before_refinement < DISCOVERY_REFINEMENT_MIN_UNIQUE_CANDIDATES
            and bool(productive_query_families)
            and bool(refinement_specs)
        )
        refinement_attempted_specs: list[dict[str, str]] = []

        if refinement_triggered:
            refinement_attempted_specs = refinement_specs[:DISCOVERY_REFINEMENT_QUERY_BUDGET]
            self._execute_harvest_queries(
                refinement_attempted_specs,
                candidate_pool=candidate_pool,
                query_diagnostics=query_diagnostics,
                search_pass="refinement",
            )

        prompt_summary = {
            "queries_attempted": len(query_diagnostics),
            "successful_queries": sum(1 for item in query_diagnostics if item.get("success")),
            "total_results": sum(int(item.get("raw_result_count", 0) or 0) for item in query_diagnostics),
            "unique_candidates": len(candidate_pool),
            "query_summaries": [
                {
                    "query": item["query"],
                    "family": item["query_family"],
                    "result_count": item["raw_result_count"],
                }
                for item in query_diagnostics
            ],
            "top_candidates": self._top_prompt_candidates(candidate_pool),
        }
        diagnostics = {
            "overview": {
                "queries_attempted": len(query_diagnostics),
                "successful_queries": prompt_summary["successful_queries"],
                "total_results": prompt_summary["total_results"],
                "unique_candidates": len(candidate_pool),
                "refinement_triggered": refinement_triggered,
                "refinement_queries_attempted": len(refinement_attempted_specs),
            },
            "queries": query_diagnostics,
            "top_candidates": self._top_prompt_candidates(candidate_pool),
            "harvested_candidates": list(candidate_pool.values()),
            "refinement": {
                "triggered": refinement_triggered,
                "reason": "sparse_first_pass" if refinement_triggered else "",
                "productive_query_families": sorted(productive_query_families),
                "attempted_queries": [spec["query"] for spec in refinement_attempted_specs],
                "unique_candidates_before": unique_candidates_before_refinement,
                "unique_candidates_after": len(candidate_pool),
                "added_unique_candidates": len(candidate_pool) - unique_candidates_before_refinement,
            },
        }
        return prompt_summary, diagnostics

    def _execute_harvest_queries(
        self,
        query_specs: list[dict[str, str]],
        *,
        candidate_pool: dict[str, dict[str, Any]],
        query_diagnostics: list[dict[str, Any]],
        search_pass: str,
    ) -> None:
        for spec in query_specs:
            query = spec["query"]
            search_result = self._search_community(
                query,
                mode="harvest",
                limit=DISCOVERY_HARVEST_QUERY_RESULT_LIMIT,
            )
            compact_payload = self._compact_search_payload(search_result.data)
            harvested_candidates = self._harvest_prompt_candidates(
                search_result.data.get("results", []),
                query=query,
                query_family=spec["query_family"],
                candidate_pool=candidate_pool,
                search_source=str(compact_payload.get("source", search_result.data.get("source", ""))).strip(),
                search_mode=str(compact_payload.get("mode", search_result.data.get("mode", "harvest"))).strip() or "harvest",
            )
            query_diagnostics.append(
                {
                    "query": query,
                    "query_family": spec["query_family"],
                    "search_pass": search_pass,
                    "success": search_result.success,
                    "search_source": compact_payload.get("source", search_result.data.get("source", "")),
                    "search_mode": compact_payload.get("mode", search_result.data.get("mode", "harvest")),
                    "result_limit": compact_payload.get(
                        "limit",
                        search_result.data.get("limit", DISCOVERY_HARVEST_QUERY_RESULT_LIMIT),
                    ),
                    "fallback_used": bool(search_result.data.get("fallback_used", False)),
                    "raw_result_count": self._count_results(search_result.data),
                    "unique_candidates_added": harvested_candidates["unique_candidates_added"],
                    "duplicate_or_unusable_results": harvested_candidates["duplicate_or_unusable_results"],
                    "error": search_result.error,
                }
            )

    def _productive_query_families(self, query_diagnostics: list[dict[str, Any]]) -> set[str]:
        productive_families: set[str] = set()
        for entry in query_diagnostics:
            if int(entry.get("unique_candidates_added", 0) or 0) <= 0:
                continue
            query_family = str(entry.get("query_family", "")).strip()
            if query_family:
                productive_families.add(query_family)
        return productive_families

    def _build_refinement_query_specs(
        self,
        session: SessionRecord,
        *,
        attempted_queries: set[str],
        productive_query_families: set[str],
    ) -> list[dict[str, str]]:
        search_inputs = self._build_search_inputs(session)
        if search_inputs is None:
            return []

        geography = search_inputs["geography"]
        offer = search_inputs["offer"]
        objective_focus = search_inputs["objective_focus"]
        core_phrase = search_inputs["core_phrase"]
        specs: list[dict[str, str]] = []

        if productive_query_families & {
            "core",
            "core_with_geography",
            "related",
            "related_with_geography",
            "city_hub",
        }:
            for city_hub in self._city_hubs_for_geography(geography)[DISCOVERY_PRIMARY_CITY_HUB_COUNT:]:
                self._append_query_spec(specs, "refined_city_hub", f"{city_hub} {core_phrase}")

        if productive_query_families & {"core", "core_with_geography", "objective", "objective_with_geography"}:
            for variant in self._build_related_phrase_variants(core_phrase, objective_focus)[DISCOVERY_PRIMARY_RELATED_VARIANT_COUNT:]:
                self._append_query_spec(specs, "refined_related_with_geography", f"{variant} {geography}")
                self._append_query_spec(specs, "refined_related", variant)

        if productive_query_families & {"core", "core_with_geography", "related", "related_with_geography"} and offer:
            self._append_query_spec(specs, "refined_offer_with_geography", f"{core_phrase} {offer} {geography}")

        return [spec for spec in specs if spec["query"] not in attempted_queries]

    def _count_results(self, payload: Any) -> int:
        if not isinstance(payload, dict):
            return 0
        results = payload.get("results", [])
        return len(results) if isinstance(results, list) else 0

    def _compact_search_payload(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        results = payload.get("results", [])
        compact_results: list[dict[str, Any]] = []
        if isinstance(results, list):
            for result in results[:5]:
                if not isinstance(result, dict):
                    continue
                compact_results.append(
                    {
                        key: result.get(key)
                        for key in DISCOVERY_SEARCH_RESULT_KEYS
                        if result.get(key) not in ("", [], {}, None)
                    }
                )

        compact_payload = {
            "query": payload.get("query"),
            "mode": payload.get("mode"),
            "limit": payload.get("limit"),
            "source": payload.get("source"),
            "results": compact_results,
        }
        return {
            key: value
            for key, value in compact_payload.items()
            if value not in ("", [], {}, None)
        }

    def _enrich_shortlist(
        self,
        shortlist_payload: dict[str, Any],
        *,
        brief_search_diagnostics: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], str]:
        communities = shortlist_payload.get("communities", [])
        if not isinstance(communities, list) or not communities:
            return shortlist_payload, ""
        harvested_candidates = []
        if brief_search_diagnostics is not None:
            raw_harvested_candidates = brief_search_diagnostics.get("harvested_candidates", [])
            if isinstance(raw_harvested_candidates, list):
                harvested_candidates = raw_harvested_candidates

        score_scale = self._score_scale(communities)
        enriched: list[dict[str, Any]] = []
        sampled_count = 0

        for community in communities:
            if not isinstance(community, dict):
                continue
            enriched_community, was_sampled = self._enrich_community(
                community,
                score_scale,
                harvested_candidates=harvested_candidates,
            )
            if was_sampled:
                sampled_count += 1
            enriched.append(enriched_community)

        enriched.sort(key=self._community_sort_key, reverse=True)
        verification_counts = self._build_verification_counts(enriched)
        shortlist_payload["communities"] = enriched
        shortlist_payload["verification_counts"] = verification_counts
        shortlist_payload["verification_summary"] = self._build_verification_summary(
            verification_counts,
            sampled_count=sampled_count,
        )
        shortlist_payload["coverage_summary"] = self._build_coverage_summary(
            enriched,
            verification_counts=verification_counts,
            brief_search_diagnostics=brief_search_diagnostics,
        )
        if brief_search_diagnostics is not None:
            shortlist_payload["search_diagnostics"] = self._finalize_search_diagnostics(
                brief_search_diagnostics,
                communities=enriched,
                accepted_shortlist_count=len(enriched),
                verification_counts=verification_counts,
            )
        summary_parts = [shortlist_payload["verification_summary"]]
        coverage_summary = shortlist_payload.get("coverage_summary", "")
        if coverage_summary:
            summary_parts.append(str(coverage_summary).strip())
        summary = " ".join(part for part in summary_parts if part)
        return shortlist_payload, summary

    def _enrich_community(
        self,
        community: dict[str, Any],
        score_scale: int,
        *,
        harvested_candidates: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        enriched = dict(community)
        notes = list(enriched.get("source_notes", [])) if isinstance(enriched.get("source_notes"), list) else []
        search_confirmed = False
        sampled = False

        matched: dict[str, Any] | None = None
        if self._community_capability is not None:
            matched, lookup_error = self._find_live_match(
                enriched,
                harvested_candidates=harvested_candidates,
            )
            if matched is not None:
                search_confirmed = True
                enriched["community_id"] = matched.get("community_id", "")
                if matched.get("username"):
                    enriched["handle"] = f"@{matched['username']}"
                enriched["live_search_match"] = matched
                enriched["match_kind"] = matched.get("match_kind", "")
                enriched["matched_query"] = matched.get("matched_query", "")
                enriched["search_source"] = matched.get("search_source", "")
                enriched["search_mode"] = matched.get("search_mode", "")
                enriched["validation_path"] = matched.get("validation_path", "")
                notes.append("Live Telegram search found a matching community entity.")
            else:
                notes.append(
                    "Live Telegram search did not confirm this community yet."
                    if not lookup_error
                    else f"Live Telegram search failed: {lookup_error}"
                )
        else:
            notes.append("Live Telegram search was unavailable, so this candidate remains a training-knowledge fallback.")

        lookup_id = self._build_profile_lookup_id(enriched, matched)
        if search_confirmed and lookup_id:
            enriched["lookup_ref"] = lookup_id
            enriched["lookup_ref_type"] = self._classify_lookup_ref_type(lookup_id)
            profile_result = self._community_capability.get_profile(lookup_id)
            if profile_result.success:
                profile = dict(profile_result.data.get("community", {}))
                enriched["live_profile"] = profile
                if profile.get("member_count") is not None:
                    enriched["member_count"] = profile.get("member_count")
                enriched["verified"] = bool(profile.get("verified", False))
                enriched["restricted"] = bool(profile.get("restricted", False))
                enriched["scam"] = bool(profile.get("scam", False))
                notes.append("Live Telegram profile metadata was attached to this candidate.")
            else:
                notes.append(f"Live Telegram profile read failed: {profile_result.error}")

        history_lookup_id = self._build_history_lookup_id(enriched)
        if search_confirmed and history_lookup_id and self._messaging_capability is not None:
            history_result = self._messaging_capability.read_messages(history_lookup_id, limit=5)
            if history_result.success:
                messages = history_result.data.get("messages", [])
                enriched["recent_activity_summary"] = self._summarize_recent_activity(messages)
                enriched["recent_tone_summary"] = self._summarize_recent_tone(messages)
                enriched["recent_message_samples"] = self._message_samples(messages)
                sampled = True
                notes.append("Sampled recent Telegram messages for current tone and activity.")
            else:
                notes.append(f"Live Telegram message sampling failed: {history_result.error}")

        verification_state = self._determine_verification_state(enriched)
        enriched["verification_state"] = verification_state
        enriched["evidence_summary"] = self._build_evidence_summary(enriched)
        enriched["source_notes"] = notes
        enriched["relevance_score"] = self._rescore_community(enriched, score_scale)
        return enriched, sampled

    def _determine_verification_state(self, community: dict[str, Any]) -> str:
        if community.get("live_profile") or community.get("recent_message_samples"):
            return VERIFICATION_STATE_LIVE_CONFIRMED
        if community.get("live_search_match"):
            return VERIFICATION_STATE_SEARCH_CONFIRMED
        return VERIFICATION_STATE_TRAINING_KNOWLEDGE_FALLBACK

    def _build_verification_counts(self, communities: list[dict[str, Any]]) -> dict[str, int]:
        counts = {
            VERIFICATION_STATE_LIVE_CONFIRMED: 0,
            VERIFICATION_STATE_SEARCH_CONFIRMED: 0,
            VERIFICATION_STATE_TRAINING_KNOWLEDGE_FALLBACK: 0,
        }
        for community in communities:
            if not isinstance(community, dict):
                continue
            state = str(community.get("verification_state", "")).strip()
            if state in counts:
                counts[state] += 1
        return counts

    def _build_verification_summary(
        self,
        verification_counts: dict[str, int],
        *,
        sampled_count: int,
    ) -> str:
        live_confirmed = verification_counts.get(VERIFICATION_STATE_LIVE_CONFIRMED, 0)
        search_confirmed = verification_counts.get(VERIFICATION_STATE_SEARCH_CONFIRMED, 0)
        fallback = verification_counts.get(VERIFICATION_STATE_TRAINING_KNOWLEDGE_FALLBACK, 0)
        return (
            "Verification status: "
            f"{live_confirmed} live-confirmed, "
            f"{search_confirmed} search-confirmed only, "
            f"{fallback} training-knowledge fallback. "
            f"Sampled recent messages for {sampled_count} communities."
        )

    def _build_coverage_summary(
        self,
        communities: list[dict[str, Any]],
        *,
        verification_counts: dict[str, int],
        brief_search_diagnostics: dict[str, Any] | None,
    ) -> str:
        notes: list[str] = []
        overview = brief_search_diagnostics.get("overview", {}) if isinstance(brief_search_diagnostics, dict) else {}
        refinement_triggered = bool(overview.get("refinement_triggered", False))
        unique_candidates = int(overview.get("unique_candidates", 0) or 0)
        broader_live_matches = sum(1 for community in communities if self._is_broader_live_match(community))
        fallback_count = verification_counts.get(VERIFICATION_STATE_TRAINING_KNOWLEDGE_FALLBACK, 0)
        exact_live_matches = sum(1 for community in communities if self._is_exact_validation_match(community))

        if refinement_triggered:
            notes.append("live Telegram coverage was sparse enough to trigger one refinement pass")
        elif unique_candidates and unique_candidates < DISCOVERY_REFINEMENT_MIN_UNIQUE_CANDIDATES:
            notes.append("live Telegram coverage stayed sparse")

        if broader_live_matches:
            label = "community relies" if broader_live_matches == 1 else "communities rely"
            notes.append(f"{broader_live_matches} shortlisted {label} on broader harvest matching")

        if fallback_count:
            label = "community remains" if fallback_count == 1 else "communities remain"
            notes.append(f"{fallback_count} shortlisted {label} training-knowledge fallback")
        elif exact_live_matches:
            notes.append("top-ranked communities skew toward direct live confirmation")

        if not notes:
            return ""

        return "Coverage notes: " + "; ".join(notes[:3]) + "."

    def _find_live_match(
        self,
        community: dict[str, Any],
        *,
        harvested_candidates: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, str]:
        last_error = ""
        harvested_match = self._pick_matching_community(
            community,
            harvested_candidates,
            matched_query="",
            search_source="",
        )
        if harvested_match is not None:
            harvested_match["validation_path"] = "harvested_pool_reuse"
            return harvested_match, ""

        for query in self._build_community_lookup_queries(community):
            search_result = self._search_community(
                query,
                mode="exact",
                limit=DISCOVERY_EXACT_QUERY_RESULT_LIMIT,
            )
            matched = self._pick_matching_community(
                community,
                search_result.data.get("results", []),
                matched_query=query,
                search_source=str(search_result.data.get("source", "")).strip(),
            )
            if search_result.success and matched is not None:
                matched["validation_path"] = "exact_requery"
                return matched, ""
            if search_result.error:
                last_error = search_result.error
        return None, last_error

    def _build_community_lookup_queries(self, community: dict[str, Any]) -> list[str]:
        handle = self._normalize_query_text(community.get("handle", ""))
        name = self._normalize_query_text(community.get("name", ""))
        geography = self._normalize_query_text(community.get("geography", ""))
        topic = self._normalize_query_text(community.get("topic", ""))
        stripped_name = self._strip_geography_terms(name, geography)

        queries: list[str] = []
        self._append_query(queries, handle)
        self._append_query(queries, f"{name} {geography}")
        self._append_query(queries, name)
        self._append_query(queries, stripped_name)
        self._append_query(queries, f"{topic} {geography}")
        self._append_query(queries, topic)
        return queries

    def _pick_matching_community(
        self,
        community: dict[str, Any],
        results: Any,
        *,
        matched_query: str,
        search_source: str,
    ) -> dict[str, Any] | None:
        if not isinstance(results, list):
            return None

        desired_handle = str(community.get("handle", "")).strip().lstrip("@").lower()
        desired_name = str(community.get("name", "")).strip().lower()
        desired_tokens = self._match_tokens(desired_name)

        for result in results:
            if not isinstance(result, dict):
                continue
            username = str(result.get("username", "")).strip().lower()
            name = str(result.get("name", "")).strip().lower()
            if desired_handle and username == desired_handle:
                return self._annotate_match(result, matched_query, search_source, "exact_handle")
            if desired_name and name == desired_name:
                return self._annotate_match(result, matched_query, search_source, "exact_name")

        for result in results:
            if not isinstance(result, dict):
                continue
            name = str(result.get("name", "")).strip().lower()
            if desired_name and desired_name in name:
                return self._annotate_match(result, matched_query, search_source, "name_contains")
            result_tokens = self._match_tokens(name)
            if self._tokens_are_close(desired_tokens, result_tokens):
                return self._annotate_match(result, matched_query, search_source, "token_close")
        return None

    def _build_profile_lookup_id(
        self,
        community: dict[str, Any],
        matched: dict[str, Any] | None,
    ) -> str:
        if matched is not None:
            username = str(matched.get("username", "")).strip()
            if username:
                return f"@{username}"
            community_id = str(matched.get("community_id", "")).strip()
            if community_id:
                return community_id

        handle = str(community.get("handle", "")).strip()
        if handle:
            return handle
        return str(community.get("community_id", "")).strip()

    def _build_history_lookup_id(self, community: dict[str, Any]) -> str:
        handle = str(community.get("handle", "")).strip()
        if handle:
            return handle
        return str(community.get("community_id", "")).strip()

    def _score_scale(self, communities: list[dict[str, Any]]) -> int:
        numeric_scores = [
            float(community.get("relevance_score", 0) or 0)
            for community in communities
            if isinstance(community, dict)
        ]
        return 100 if any(score > 10 for score in numeric_scores) else 10

    def _rescore_community(self, community: dict[str, Any], score_scale: int) -> int:
        base_score = float(community.get("relevance_score", 0) or 0)
        delta = 0.0
        verification_state = str(community.get("verification_state", "")).strip()
        match_kind = str(community.get("match_kind", "")).strip()
        search_mode = str(community.get("search_mode", "")).strip()
        validation_path = str(community.get("validation_path", "")).strip()

        if community.get("member_count"):
            delta += 0.5 if score_scale == 10 else 5
        if community.get("recent_message_samples"):
            delta += 0.5 if score_scale == 10 else 5
        if community.get("verified"):
            delta += 0.25 if score_scale == 10 else 3
        if community.get("restricted"):
            delta -= 0.5 if score_scale == 10 else 6
        if community.get("scam"):
            delta -= 1 if score_scale == 10 else 12
        if verification_state == VERIFICATION_STATE_LIVE_CONFIRMED:
            delta += 0.75 if score_scale == 10 else 8
        elif verification_state == VERIFICATION_STATE_SEARCH_CONFIRMED:
            delta += 0.25 if score_scale == 10 else 3
        elif verification_state == VERIFICATION_STATE_TRAINING_KNOWLEDGE_FALLBACK:
            delta -= 0.75 if score_scale == 10 else 8

        if match_kind == "exact_handle":
            delta += 0.35 if score_scale == 10 else 4
        elif match_kind == "exact_name":
            delta += 0.2 if score_scale == 10 else 2
        elif match_kind in APPROXIMATE_MATCH_KINDS:
            delta -= 0.15 if score_scale == 10 else 2

        if search_mode == "exact" or validation_path == "exact_requery":
            delta += 0.2 if score_scale == 10 else 2
        elif search_mode == "harvest":
            delta -= 0.1 if score_scale == 10 else 1

        rescored = base_score + delta
        return int(max(0, min(score_scale, round(rescored))))

    def _community_sort_key(self, community: dict[str, Any]) -> tuple[float, int, int, int, int, int, int]:
        return (
            float(community.get("relevance_score", 0) or 0),
            self._verification_rank(community),
            self._validation_precision_rank(community),
            self._match_kind_rank(str(community.get("match_kind", "")).strip()),
            int(bool(community.get("recent_message_samples"))),
            int(bool(community.get("live_profile"))),
            int(community.get("member_count") or 0),
        )

    def _verification_rank(self, community: dict[str, Any]) -> int:
        verification_state = str(community.get("verification_state", "")).strip()
        if verification_state == VERIFICATION_STATE_LIVE_CONFIRMED:
            return 3
        if verification_state == VERIFICATION_STATE_SEARCH_CONFIRMED:
            return 2
        return 1 if verification_state == VERIFICATION_STATE_TRAINING_KNOWLEDGE_FALLBACK else 0

    def _validation_precision_rank(self, community: dict[str, Any]) -> int:
        if self._is_exact_validation_match(community):
            return 3
        if self._is_broader_live_match(community):
            return 1
        if community.get("live_search_match"):
            return 2
        return 0

    def _match_kind_rank(self, match_kind: str) -> int:
        if match_kind == "exact_handle":
            return 4
        if match_kind == "exact_name":
            return 3
        if match_kind == "name_contains":
            return 2
        if match_kind == "token_close":
            return 1
        return 0

    def _build_evidence_summary(self, community: dict[str, Any]) -> str:
        verification_state = str(community.get("verification_state", "")).strip()
        if verification_state == VERIFICATION_STATE_TRAINING_KNOWLEDGE_FALLBACK:
            return "No live Telegram match yet; training-knowledge fallback only."

        if self._is_exact_validation_match(community):
            summary = "Exact live match"
        elif self._is_broader_live_match(community):
            summary = "Broader harvested live match"
        else:
            summary = "Live match"

        if verification_state == VERIFICATION_STATE_SEARCH_CONFIRMED:
            return f"{summary}; profile or recent-message validation is still missing."

        details: list[str] = []
        if community.get("live_profile"):
            details.append("profile attached")
        if community.get("recent_message_samples"):
            details.append("recent messages sampled")
        if not details:
            return f"{summary}."
        return f"{summary}; " + "; ".join(details) + "."

    def _summarize_recent_activity(self, messages: Any) -> str:
        if not isinstance(messages, list) or not messages:
            return "No recent Telegram messages were available in the sampled window."
        non_empty = [message for message in messages if str(message.get("text", "")).strip()]
        return (
            f"Sampled {len(messages)} recent messages, with {len(non_empty)} containing readable text."
        )

    def _summarize_recent_tone(self, messages: Any) -> str:
        if not isinstance(messages, list) or not messages:
            return "Recent tone could not be sampled from live Telegram history."
        text_lengths = [
            len(str(message.get("text", "")).strip())
            for message in messages
            if str(message.get("text", "")).strip()
        ]
        if not text_lengths:
            return "Recent posts were mostly empty or media-only."
        average_length = sum(text_lengths) / len(text_lengths)
        if average_length >= 120:
            return "Recent posts skew toward longer discussion-style messages."
        if average_length >= 40:
            return "Recent posts look like short conversational updates."
        return "Recent posts skew toward brief announcements or low-context replies."

    def _message_samples(self, messages: Any) -> list[str]:
        if not isinstance(messages, list):
            return []
        samples: list[str] = []
        for message in messages:
            text = str(message.get("text", "")).strip()
            if not text:
                continue
            samples.append(text[:140])
            if len(samples) == 3:
                break
        return samples

    def _append_query(self, queries: list[str], query: str) -> None:
        normalized = self._normalize_query_text(query)
        if normalized and normalized not in queries:
            queries.append(normalized)

    def _append_query_spec(self, specs: list[dict[str, str]], query_family: str, query: str) -> None:
        normalized = self._normalize_query_text(query)
        if not normalized:
            return
        if any(spec["query"] == normalized for spec in specs):
            return
        specs.append({"query": normalized, "query_family": query_family})

    def _normalize_query_text(self, value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    def _build_related_phrase_variants(self, core_phrase: str, objective_focus: str) -> list[str]:
        variants: list[str] = []
        lower_core = core_phrase.lower()

        if "founders" in lower_core:
            variants.append(re.sub(r"\bfounders\b", "startup founders", core_phrase, flags=re.IGNORECASE))
            variants.append(re.sub(r"\bfounders\b", "builders", core_phrase, flags=re.IGNORECASE))
            variants.append(re.sub(r"\bfounders\b", "entrepreneurs", core_phrase, flags=re.IGNORECASE))

        if objective_focus and objective_focus.lower() != lower_core:
            variants.append(objective_focus)

        deduped: list[str] = []
        for variant in variants:
            normalized = self._normalize_query_text(variant)
            if normalized and normalized.lower() != lower_core and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    def _city_hubs_for_geography(self, geography: str) -> tuple[str, ...]:
        geography_tokens = self._match_tokens(geography)
        for geography_key, city_hubs in _GEOGRAPHY_CITY_HUBS.items():
            if geography_key in geography_tokens:
                return city_hubs
        return ()

    def _extract_objective_focus(self, objective: str) -> str:
        normalized = self._normalize_query_text(objective)
        lower = normalized.lower()
        for marker in (" communities for ", " community for ", " groups for ", " group for ", " channels for ", " channel for ", " for "):
            marker_index = lower.find(marker)
            if marker_index != -1:
                return normalized[marker_index + len(marker) :].strip()
        return normalized

    def _candidate_pool_key(self, candidate: dict[str, Any]) -> str:
        username = str(candidate.get("username", "")).strip().lower()
        if username:
            return f"username:{username}"
        community_id = str(candidate.get("community_id", "")).strip()
        if community_id:
            return f"community_id:{community_id}"
        name = str(candidate.get("name", "")).strip().lower()
        return f"name:{name}"

    def _harvest_prompt_candidates(
        self,
        results: Any,
        *,
        query: str,
        query_family: str,
        candidate_pool: dict[str, dict[str, Any]],
        search_source: str,
        search_mode: str,
    ) -> dict[str, int]:
        unique_candidates_added = 0
        duplicate_or_unusable_results = 0

        if not isinstance(results, list):
            return {
                "unique_candidates_added": unique_candidates_added,
                "duplicate_or_unusable_results": duplicate_or_unusable_results,
            }

        for result in results:
            if not isinstance(result, dict):
                duplicate_or_unusable_results += 1
                continue

            candidate = {
                key: result.get(key)
                for key in DISCOVERY_SEARCH_RESULT_KEYS
                if result.get(key) not in ("", [], {}, None)
            }
            candidate_key = self._candidate_pool_key(candidate)
            if candidate_key.endswith(":"):
                duplicate_or_unusable_results += 1
                continue

            result_search_source = str(result.get("search_source", "")).strip() or search_source
            result_search_mode = str(result.get("search_mode", "")).strip() or search_mode
            existing = candidate_pool.get(candidate_key)
            if existing is None:
                existing = dict(candidate)
                existing["matched_queries"] = [query]
                existing["query_families"] = [query_family]
                existing["matched_query"] = query
                existing["search_source"] = result_search_source
                existing["search_mode"] = result_search_mode
                candidate_pool[candidate_key] = existing
                unique_candidates_added += 1
                continue

            duplicate_or_unusable_results += 1
            if query not in existing["matched_queries"]:
                existing["matched_queries"].append(query)
            if query_family not in existing["query_families"]:
                existing["query_families"].append(query_family)

        return {
            "unique_candidates_added": unique_candidates_added,
            "duplicate_or_unusable_results": duplicate_or_unusable_results,
        }

    def _top_prompt_candidates(self, candidate_pool: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        ranked_candidates = sorted(
            candidate_pool.values(),
            key=lambda candidate: (
                int(bool(candidate.get("verified"))),
                int(candidate.get("member_count") or 0),
                len(candidate.get("matched_queries", [])),
            ),
            reverse=True,
        )
        return [
            {
                key: candidate.get(key)
                for key in DISCOVERY_TOP_CANDIDATE_KEYS
                if candidate.get(key) not in ("", [], {}, None)
            }
            for candidate in ranked_candidates[:DISCOVERY_TOP_CANDIDATE_BUDGET]
        ]

    def _annotate_match(
        self,
        result: dict[str, Any],
        matched_query: str,
        search_source: str,
        match_kind: str,
    ) -> dict[str, Any]:
        annotated = dict(result)
        annotated["matched_query"] = matched_query or str(result.get("matched_query", "")).strip()
        annotated["search_source"] = search_source or str(result.get("search_source", "")).strip()
        if result.get("search_mode") not in ("", [], {}, None):
            annotated["search_mode"] = result.get("search_mode")
        annotated["match_kind"] = match_kind
        return annotated

    def _classify_lookup_ref_type(self, lookup_ref: str) -> str:
        if lookup_ref.startswith("@"):
            return "username"
        if lookup_ref.isdigit():
            return "community_id"
        return "name"

    def _finalize_search_diagnostics(
        self,
        brief_search_diagnostics: dict[str, Any],
        *,
        communities: list[dict[str, Any]],
        accepted_shortlist_count: int,
        verification_counts: dict[str, int],
    ) -> dict[str, Any]:
        diagnostics = dict(brief_search_diagnostics)
        diagnostics.pop("harvested_candidates", None)
        overview = dict(diagnostics.get("overview", {}))
        overview["accepted_shortlist_count"] = accepted_shortlist_count
        overview["live_confirmed"] = verification_counts.get(VERIFICATION_STATE_LIVE_CONFIRMED, 0)
        overview["search_confirmed"] = verification_counts.get(VERIFICATION_STATE_SEARCH_CONFIRMED, 0)
        overview["training_knowledge_fallback"] = verification_counts.get(
            VERIFICATION_STATE_TRAINING_KNOWLEDGE_FALLBACK,
            0,
        )
        diagnostics["overview"] = overview
        diagnostics["harvest"] = {
            "queries_attempted": overview.get("queries_attempted", 0),
            "successful_queries": overview.get("successful_queries", 0),
            "unique_candidates": overview.get("unique_candidates", 0),
            "top_candidate_count": len(diagnostics.get("top_candidates", [])),
            "first_pass_queries": sum(1 for item in diagnostics.get("queries", []) if item.get("search_pass") == "first_pass"),
            "refinement_queries": sum(1 for item in diagnostics.get("queries", []) if item.get("search_pass") == "refinement"),
            "fallback_queries": sum(1 for item in diagnostics.get("queries", []) if item.get("fallback_used")),
        }
        diagnostics["validation"] = self._build_validation_diagnostics(
            communities,
            accepted_shortlist_count=accepted_shortlist_count,
            verification_counts=verification_counts,
        )
        return diagnostics

    def _build_validation_diagnostics(
        self,
        communities: list[dict[str, Any]],
        *,
        accepted_shortlist_count: int,
        verification_counts: dict[str, int],
    ) -> dict[str, int]:
        return {
            "accepted_shortlist_count": accepted_shortlist_count,
            "live_confirmed": verification_counts.get(VERIFICATION_STATE_LIVE_CONFIRMED, 0),
            "search_confirmed": verification_counts.get(VERIFICATION_STATE_SEARCH_CONFIRMED, 0),
            "training_knowledge_fallback": verification_counts.get(VERIFICATION_STATE_TRAINING_KNOWLEDGE_FALLBACK, 0),
            "exact_validation_matches": sum(1 for community in communities if self._is_exact_validation_match(community)),
            "broader_live_matches": sum(1 for community in communities if self._is_broader_live_match(community)),
            "harvest_pool_matches": sum(1 for community in communities if community.get("validation_path") == "harvested_pool_reuse"),
            "exact_requery_matches": sum(1 for community in communities if community.get("validation_path") == "exact_requery"),
            "profile_attached": sum(1 for community in communities if community.get("live_profile")),
            "recent_message_samples": sum(1 for community in communities if community.get("recent_message_samples")),
        }

    def _is_exact_validation_match(self, community: dict[str, Any]) -> bool:
        match_kind = str(community.get("match_kind", "")).strip()
        search_mode = str(community.get("search_mode", "")).strip()
        validation_path = str(community.get("validation_path", "")).strip()
        return match_kind in EXACT_MATCH_KINDS and (search_mode == "exact" or validation_path == "exact_requery")

    def _is_broader_live_match(self, community: dict[str, Any]) -> bool:
        if not community.get("live_search_match"):
            return False
        if self._is_exact_validation_match(community):
            return False
        match_kind = str(community.get("match_kind", "")).strip()
        search_mode = str(community.get("search_mode", "")).strip()
        return search_mode == "harvest" or match_kind in APPROXIMATE_MATCH_KINDS or bool(match_kind)

    def _search_community(self, query: str, *, mode: str, limit: int) -> Any:
        return self._community_capability.search(query, mode=mode, limit=limit)

    def _match_tokens(self, value: str) -> set[str]:
        tokens: set[str] = set()
        for raw_token in re.split(r"[^a-z0-9]+", value.lower()):
            if not raw_token:
                continue
            token = self._canonicalize_token(raw_token)
            if token and token not in _MATCH_STOPWORDS:
                tokens.add(token)
        return tokens

    def _canonicalize_token(self, token: str) -> str:
        if token.endswith("ies") and len(token) > 4:
            token = f"{token[:-3]}y"
        elif token.endswith("s") and len(token) > 4:
            token = token[:-1]
        if token == "european":
            return "europe"
        return token

    def _tokens_are_close(self, desired_tokens: set[str], result_tokens: set[str]) -> bool:
        if not desired_tokens or not result_tokens:
            return False
        overlap = desired_tokens & result_tokens
        if len(overlap) < 2:
            return False
        smaller_group_size = min(len(desired_tokens), len(result_tokens))
        return len(overlap) / smaller_group_size >= 0.67

    def _strip_geography_terms(self, phrase: str, geography: str) -> str:
        if not phrase or not geography:
            return ""

        geography_tokens = self._match_tokens(geography)
        if "europe" in geography_tokens:
            geography_tokens.add("eu")

        filtered_tokens: list[str] = []
        for raw_token in phrase.split():
            normalized_token = re.sub(r"[^a-z0-9]+", "", raw_token.lower())
            canonical_token = self._canonicalize_token(normalized_token)
            if canonical_token and canonical_token not in geography_tokens:
                filtered_tokens.append(raw_token)
        return " ".join(filtered_tokens)
