"""Pure recent-history selection policy over complete exchanges."""

from __future__ import annotations

import json
from dataclasses import dataclass

from jarvis.history.context_budget import PromptEstimateMaterial, PromptTokenEstimator


@dataclass(frozen=True)
class ConversationTurn:
    role: str
    text: str
    media_b64: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecentHistoryExchange:
    turns: tuple[ConversationTurn, ...]

    def __post_init__(self) -> None:
        if not self.turns:
            raise ValueError("recent history exchange must contain at least one turn")


@dataclass(frozen=True)
class RecentHistorySelection:
    """Selected recent history plus explicit observability metadata."""

    prefix_turns: tuple[ConversationTurn, ...]
    exchanges: tuple[RecentHistoryExchange, ...]
    estimated_tokens: int
    max_tokens: int
    total_exchange_count: int
    selected_exchange_count: int
    dropped_exchange_count: int
    requested_minimum_recent_exchanges: int
    minimum_recent_exchanges_met: bool
    truncated: bool
    blank_context_cleared: bool

    @property
    def turns(self) -> tuple[ConversationTurn, ...]:
        selected: list[ConversationTurn] = list(self.prefix_turns)
        for exchange in self.exchanges:
            selected.extend(exchange.turns)
        return tuple(selected)

    @property
    def available_tokens(self) -> int:
        return self.max_tokens - self.estimated_tokens


def turns_as_messages(
    turns: tuple[ConversationTurn, ...] | list[ConversationTurn],
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for turn in turns:
        message: dict[str, object] = {"role": turn.role, "content": turn.text}
        if turn.media_b64:
            message["images"] = list(turn.media_b64)
        messages.append(message)
    return messages


def select_recent_history(
    turns: tuple[ConversationTurn, ...] | list[ConversationTurn],
    *,
    estimator: PromptTokenEstimator,
    max_tokens: int,
    minimum_recent_exchanges: int,
    blank_context: bool = False,
) -> RecentHistorySelection:
    if max_tokens < 0:
        raise ValueError("max_tokens must not be negative")
    if minimum_recent_exchanges <= 0:
        raise ValueError("minimum_recent_exchanges must be positive")
    if blank_context:
        return RecentHistorySelection(
            prefix_turns=(),
            exchanges=(),
            estimated_tokens=0,
            max_tokens=max_tokens,
            total_exchange_count=0,
            selected_exchange_count=0,
            dropped_exchange_count=0,
            requested_minimum_recent_exchanges=minimum_recent_exchanges,
            minimum_recent_exchanges_met=False,
            truncated=False,
            blank_context_cleared=True,
        )

    prefix_turns, exchanges = _split_complete_exchanges(tuple(turns))
    if not exchanges:
        prefix_tokens = estimate_history_contribution_tokens(prefix_turns, estimator)
        if prefix_tokens <= max_tokens:
            return RecentHistorySelection(
                prefix_turns=prefix_turns,
                exchanges=(),
                estimated_tokens=prefix_tokens,
                max_tokens=max_tokens,
                total_exchange_count=0,
                selected_exchange_count=0,
                dropped_exchange_count=0,
                requested_minimum_recent_exchanges=minimum_recent_exchanges,
                minimum_recent_exchanges_met=False,
                truncated=False,
                blank_context_cleared=False,
            )
        return RecentHistorySelection(
            prefix_turns=(),
            exchanges=(),
            estimated_tokens=0,
            max_tokens=max_tokens,
            total_exchange_count=0,
            selected_exchange_count=0,
            dropped_exchange_count=0,
            requested_minimum_recent_exchanges=minimum_recent_exchanges,
            minimum_recent_exchanges_met=False,
            truncated=bool(prefix_turns),
            blank_context_cleared=False,
        )

    exchange_metrics = tuple(_exchange_metrics(exchange) for exchange in exchanges)

    suffix_bytes = [0] * (len(exchanges) + 1)
    suffix_message_counts = [0] * (len(exchanges) + 1)
    for index in range(len(exchanges) - 1, -1, -1):
        suffix_bytes[index] = (
            suffix_bytes[index + 1] + exchange_metrics[index].utf8_bytes
        )
        suffix_message_counts[index] = (
            suffix_message_counts[index + 1] + exchange_metrics[index].message_count
        )

    selected_start = len(exchanges)
    selected_tokens = 0
    for start_index in range(len(exchanges) + 1):
        candidate_tokens = _estimate_message_contribution_tokens(
            suffix_bytes[start_index],
            suffix_message_counts[start_index],
            estimator,
        )
        if candidate_tokens <= max_tokens:
            selected_start = start_index
            selected_tokens = candidate_tokens
            break

    selected_exchanges = exchanges[selected_start:]
    return RecentHistorySelection(
        prefix_turns=(),
        exchanges=selected_exchanges,
        estimated_tokens=selected_tokens,
        max_tokens=max_tokens,
        total_exchange_count=len(exchanges),
        selected_exchange_count=len(selected_exchanges),
        dropped_exchange_count=selected_start,
        requested_minimum_recent_exchanges=minimum_recent_exchanges,
        minimum_recent_exchanges_met=len(selected_exchanges)
        >= minimum_recent_exchanges,
        truncated=selected_start > 0,
        blank_context_cleared=False,
    )


def estimate_history_contribution_tokens(
    turns: tuple[ConversationTurn, ...] | list[ConversationTurn],
    estimator: PromptTokenEstimator,
) -> int:
    turns = tuple(turns)
    return _estimate_message_contribution_tokens(
        _message_sequence_utf8_bytes(turns),
        len(turns),
        estimator,
    )


def _split_complete_exchanges(
    turns: tuple[ConversationTurn, ...],
) -> tuple[tuple[ConversationTurn, ...], tuple[RecentHistoryExchange, ...]]:
    prefix: list[ConversationTurn] = []
    exchanges: list[RecentHistoryExchange] = []
    current_exchange: list[ConversationTurn] = []
    seen_user = False

    for turn in turns:
        if turn.role == "user":
            if current_exchange:
                exchanges.append(RecentHistoryExchange(tuple(current_exchange)))
            current_exchange = []
            if not seen_user and prefix:
                current_exchange.extend(prefix)
                prefix = []
            current_exchange.append(turn)
            seen_user = True
            continue
        if seen_user:
            current_exchange.append(turn)
            continue
        prefix.append(turn)

    if current_exchange:
        exchanges.append(RecentHistoryExchange(tuple(current_exchange)))
    return tuple(prefix), tuple(exchanges)


@dataclass(frozen=True)
class _ExchangeMetrics:
    utf8_bytes: int
    message_count: int


def _exchange_metrics(exchange: RecentHistoryExchange) -> _ExchangeMetrics:
    return _ExchangeMetrics(
        utf8_bytes=_message_sequence_utf8_bytes(exchange.turns),
        message_count=len(exchange.turns),
    )


def _message_sequence_utf8_bytes(turns: tuple[ConversationTurn, ...]) -> int:
    if not turns:
        return 0
    message_json = tuple(_canonical_message_json(turn) for turn in turns)
    total = sum(len(item.encode("utf-8")) for item in message_json)
    return total + (len(message_json) - 1)


def _canonical_message_json(turn: ConversationTurn) -> str:
    return json.dumps(
        turns_as_messages((turn,))[0],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _estimate_message_contribution_tokens(
    utf8_bytes: int,
    message_count: int,
    estimator: PromptTokenEstimator,
) -> int:
    base = estimator.estimate_tokens(
        PromptEstimateMaterial(
            canonical_utf8_bytes=0,
            message_count=0,
            tool_count=0,
        )
    )
    estimated = estimator.estimate_tokens(
        PromptEstimateMaterial(
            canonical_utf8_bytes=utf8_bytes,
            message_count=message_count,
            tool_count=0,
        )
    )
    return max(0, estimated - base)
