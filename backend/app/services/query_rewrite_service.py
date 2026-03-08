from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.exceptions import QueryRewriteError
from app.services.chat_completion_service import ChatCompletionService
from app.utils.retry import get_api_error_status_code, is_timeout_api_exception

QUESTION_SUFFIXES = (
    "怎么处理",
    "如何处理",
    "怎么办",
    "怎么解决",
    "如何解决",
    "怎么排查",
    "如何排查",
)
COMPOUND_SEPARATORS = ("以及", "并且", "同时", "分别", "和", "，", ",", "、", ";")


@dataclass(slots=True)
class RewritePlan:
    strategy: str
    canonical_query: str
    generated_queries: list[str]
    final_queries: list[str]
    reasons: list[str] = field(default_factory=list)
    fallback_used: bool = False
    model: str | None = None
    enabled: bool = True

    @classmethod
    def passthrough(
        cls,
        query: str,
        *,
        enabled: bool,
        reason: str,
        fallback_used: bool = False,
        model: str | None = None,
    ) -> RewritePlan:
        return cls(
            strategy="bypass",
            canonical_query=query,
            generated_queries=[],
            final_queries=[query],
            reasons=[reason],
            fallback_used=fallback_used,
            model=model,
            enabled=enabled,
        )

    def to_debug_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "strategy": self.strategy,
            "canonical_query": self.canonical_query,
            "generated_queries": self.generated_queries,
            "final_queries": self.final_queries,
            "reasons": self.reasons,
            "fallback_used": self.fallback_used,
            "model": self.model,
        }


class QueryRewriteService:
    """Rewrite or decompose user queries before retrieval fanout."""

    def __init__(
        self,
        chat_service: ChatCompletionService | None = None,
        settings: Settings | None = None,
    ):
        self._settings = settings or get_settings()
        self._chat_service = chat_service or ChatCompletionService(settings=self._settings)
        self._cache: dict[str, tuple[float, RewritePlan]] = {}

    async def build_plan(self, query: str) -> RewritePlan:
        normalized_query = self._normalize(query)
        cached = self._get_cached(normalized_query)
        if cached is not None:
            return cached

        strategy = self._resolve_strategy(normalized_query)
        if strategy == "bypass":
            plan = RewritePlan.passthrough(
                normalized_query,
                enabled=True,
                reason="precision_query",
                model=self._settings.query_rewrite_model,
            )
            self._store_cached(normalized_query, plan)
            return plan

        reasons = [f"classifier:{strategy}"]
        canonical_query = normalized_query
        generated_queries: list[str] = []
        fallback_used = False

        try:
            payload = await self._chat_service.complete_json(
                system_prompt=self._build_system_prompt(),
                user_prompt=normalized_query,
            )
            payload_strategy = payload.get("strategy")
            if payload_strategy in {"bypass", "expand", "decompose"}:
                strategy = payload_strategy
            canonical_query = self._normalize(payload.get("canonical_query") or normalized_query)
            generated_queries = self._sanitize_generated_queries(
                payload.get("queries", []),
                normalized_query,
                canonical_query,
            )
            reasons.append("llm")
        except QueryRewriteError as exc:
            fallback_used = True
            reasons.append(self._fallback_reason(exc))

        if strategy == "decompose" and not generated_queries:
            generated_queries = self._heuristic_decompose(normalized_query)
            if generated_queries:
                fallback_used = True
                reasons.append("heuristic_decompose")

        final_queries = self._compose_final_queries(
            normalized_query,
            canonical_query,
            generated_queries,
        )
        if len(final_queries) == 1:
            strategy = "bypass"

        plan = RewritePlan(
            strategy=strategy,
            canonical_query=canonical_query,
            generated_queries=generated_queries,
            final_queries=final_queries,
            reasons=reasons,
            fallback_used=fallback_used,
            model=self._settings.query_rewrite_model,
            enabled=True,
        )
        self._store_cached(normalized_query, plan)
        return plan

    def _resolve_strategy(self, query: str) -> str:
        mode = self._settings.query_rewrite_mode
        if mode in {"expand", "decompose", "bypass"}:
            return mode
        if self._looks_like_precise_query(query):
            return "bypass"
        if self._looks_like_compound_query(query):
            return "decompose"
        return "expand"

    def _looks_like_precise_query(self, query: str) -> bool:
        upper_query = query.upper()
        precise_patterns = [
            r"\b[A-Z]{2,}[-_ ]?\d{2,}\b",
            r"\b(?:HTTP|ERR|SQL|TLS|SSL|DNS)[-_ ]?\d*\b",
            r"/[A-Za-z0-9_./-]+",
            r"`[^`]+`",
        ]
        return any(re.search(pattern, upper_query) for pattern in precise_patterns)

    def _looks_like_compound_query(self, query: str) -> bool:
        if not any(suffix in query for suffix in QUESTION_SUFFIXES):
            return False
        return any(token in query for token in COMPOUND_SEPARATORS)

    def _heuristic_decompose(self, query: str) -> list[str]:
        suffix = next((item for item in QUESTION_SUFFIXES if query.endswith(item)), "")
        stem = query[:-len(suffix)] if suffix else query
        stem = stem.strip("，、 ")
        if not stem:
            return []

        parts = [stem]
        for separator in COMPOUND_SEPARATORS:
            if separator in stem:
                parts = [item.strip() for item in stem.split(separator) if item.strip()]
                if len(parts) > 1:
                    break

        results = []
        for part in parts:
            candidate = f"{part}{suffix}".strip()
            if candidate and candidate != query:
                results.append(candidate)
        return results[: max(self._settings.query_rewrite_max_queries - 1, 0)]

    def _compose_final_queries(
        self,
        raw_query: str,
        canonical_query: str,
        generated_queries: list[str],
    ) -> list[str]:
        final_queries: list[str] = []
        for candidate in [raw_query, canonical_query, *generated_queries]:
            normalized_candidate = self._normalize(candidate)
            if normalized_candidate and normalized_candidate not in final_queries:
                final_queries.append(normalized_candidate)
            if len(final_queries) >= self._settings.query_rewrite_max_queries:
                break
        return final_queries

    def _sanitize_generated_queries(
        self,
        queries: object,
        raw_query: str,
        canonical_query: str,
    ) -> list[str]:
        if not isinstance(queries, list):
            return []

        generated_queries: list[str] = []
        for item in queries:
            normalized = self._normalize(item if isinstance(item, str) else "")
            if not normalized or normalized in {raw_query, canonical_query}:
                continue
            if normalized not in generated_queries:
                generated_queries.append(normalized)
        return generated_queries[: max(self._settings.query_rewrite_max_queries - 1, 0)]

    def _build_system_prompt(self) -> str:
        return (
            "You rewrite enterprise search queries for retrieval only. "
            "Return strict JSON with keys: strategy, canonical_query, queries. "
            "strategy must be one of bypass, expand, decompose. "
            "queries must be short search queries, not answers."
        )

    def _fallback_reason(self, exc: QueryRewriteError) -> str:
        if is_timeout_api_exception(exc):
            return "rewrite_timeout"
        status_code = get_api_error_status_code(exc)
        if status_code in {502, 503, 504}:
            return "rewrite_5xx"
        return "rewrite_error"

    def _normalize(self, query: str) -> str:
        return re.sub(r"\s+", " ", query).strip()

    def _get_cached(self, query: str) -> RewritePlan | None:
        cached = self._cache.get(query)
        if cached is None:
            return None
        expires_at, plan = cached
        if expires_at < time.monotonic():
            self._cache.pop(query, None)
            return None
        return plan

    def _store_cached(self, query: str, plan: RewritePlan) -> None:
        self._cache[query] = (time.monotonic() + self._settings.query_rewrite_cache_ttl, plan)
