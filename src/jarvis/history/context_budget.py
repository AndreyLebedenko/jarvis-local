"""Pure context-budget policy for bounded Ollama prompts."""

from dataclasses import dataclass
from typing import Protocol


class ContextBudgetError(Exception):
    """Raised when a prompt candidate cannot fit the configured budget."""


CONSERVATIVE_UTF8_ESTIMATOR_FORMULA = (
    "ceil(canonical_utf8_bytes / 2) + 32 + 12 * message_count + 24 * tool_count"
)


@dataclass(frozen=True)
class PromptEstimateMaterial:
    canonical_utf8_bytes: int
    message_count: int
    tool_count: int = 0

    def __post_init__(self) -> None:
        _require_non_negative("canonical_utf8_bytes", self.canonical_utf8_bytes)
        _require_non_negative("message_count", self.message_count)
        _require_non_negative("tool_count", self.tool_count)


class PromptTokenEstimator(Protocol):
    def estimate_tokens(self, material: PromptEstimateMaterial) -> int:
        """Estimate prompt tokens before backend dispatch."""


@dataclass(frozen=True)
class ConservativeUtf8TokenEstimator:
    """Task v1.8.0-3's approved no-dependency Gemma4 estimator."""

    def estimate_tokens(self, material: PromptEstimateMaterial) -> int:
        return (
            _ceil_div(material.canonical_utf8_bytes, 2)
            + 32
            + 12 * material.message_count
            + 24 * material.tool_count
        )


@dataclass(frozen=True)
class ContextBudgetLimits:
    prompt_capacity_tokens: int
    recent_history_max_tokens: int
    automatic_retrieval_max_tokens: int
    tool_result_reserve_tokens: int
    reasoning_generation_reserve_tokens: int
    estimator_safety_margin_tokens: int
    minimum_recent_exchanges: int

    def __post_init__(self) -> None:
        for name, value in (
            ("prompt_capacity_tokens", self.prompt_capacity_tokens),
            ("recent_history_max_tokens", self.recent_history_max_tokens),
            ("automatic_retrieval_max_tokens", self.automatic_retrieval_max_tokens),
            ("tool_result_reserve_tokens", self.tool_result_reserve_tokens),
            (
                "reasoning_generation_reserve_tokens",
                self.reasoning_generation_reserve_tokens,
            ),
            ("estimator_safety_margin_tokens", self.estimator_safety_margin_tokens),
            ("minimum_recent_exchanges", self.minimum_recent_exchanges),
        ):
            _require_positive(name, value)
        _require_prompt_room(
            self.prompt_capacity_tokens,
            self.tool_result_reserve_tokens,
            self.estimator_safety_margin_tokens,
        )


@dataclass(frozen=True)
class ContextBudgetRequest:
    fixed_prompt_input_tokens: int
    recent_history_tokens: int
    automatic_retrieval_tokens: int

    def __post_init__(self) -> None:
        _require_non_negative(
            "fixed_prompt_input_tokens", self.fixed_prompt_input_tokens
        )
        _require_non_negative("recent_history_tokens", self.recent_history_tokens)
        _require_non_negative(
            "automatic_retrieval_tokens", self.automatic_retrieval_tokens
        )


@dataclass(frozen=True)
class ContextBudgetAllocation:
    fixed_prompt_input_tokens: int
    recent_history_tokens: int
    automatic_retrieval_tokens: int
    tool_result_reserve_tokens: int
    reasoning_generation_reserve_tokens: int
    estimator_safety_margin_tokens: int
    prompt_capacity_tokens: int

    @property
    def prompt_input_tokens(self) -> int:
        return (
            self.fixed_prompt_input_tokens
            + self.recent_history_tokens
            + self.automatic_retrieval_tokens
            + self.tool_result_reserve_tokens
            + self.estimator_safety_margin_tokens
        )

    @property
    def available_prompt_tokens(self) -> int:
        return self.prompt_capacity_tokens - self.prompt_input_tokens


def allocate_context_budget(
    limits: ContextBudgetLimits, request: ContextBudgetRequest
) -> ContextBudgetAllocation:
    if request.recent_history_tokens > limits.recent_history_max_tokens:
        raise ContextBudgetError(
            "recent history request exceeds its configured maximum: "
            f"{request.recent_history_tokens} > {limits.recent_history_max_tokens}"
        )
    if request.automatic_retrieval_tokens > limits.automatic_retrieval_max_tokens:
        raise ContextBudgetError(
            "automatic retrieval request exceeds its configured maximum: "
            f"{request.automatic_retrieval_tokens} > "
            f"{limits.automatic_retrieval_max_tokens}"
        )

    allocation = ContextBudgetAllocation(
        fixed_prompt_input_tokens=request.fixed_prompt_input_tokens,
        recent_history_tokens=request.recent_history_tokens,
        automatic_retrieval_tokens=request.automatic_retrieval_tokens,
        tool_result_reserve_tokens=limits.tool_result_reserve_tokens,
        reasoning_generation_reserve_tokens=limits.reasoning_generation_reserve_tokens,
        estimator_safety_margin_tokens=limits.estimator_safety_margin_tokens,
        prompt_capacity_tokens=limits.prompt_capacity_tokens,
    )
    if allocation.prompt_input_tokens > limits.prompt_capacity_tokens:
        raise ContextBudgetError(
            "prompt budget exceeded: "
            f"{allocation.prompt_input_tokens} > {limits.prompt_capacity_tokens}"
        )
    return allocation


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ContextBudgetError(f"{name} must not be negative, got {value!r}")


def _require_positive(name: str, value: int) -> None:
    if value <= 0:
        raise ContextBudgetError(f"{name} must be positive, got {value!r}")


def _require_prompt_room(
    prompt_capacity_tokens: int,
    tool_result_reserve_tokens: int,
    estimator_safety_margin_tokens: int,
) -> None:
    mandatory_prompt_reserves = (
        tool_result_reserve_tokens + estimator_safety_margin_tokens
    )
    if mandatory_prompt_reserves >= prompt_capacity_tokens:
        raise ContextBudgetError(
            "mandatory prompt reserves must leave room for fixed prompt input: "
            f"{mandatory_prompt_reserves} >= {prompt_capacity_tokens}"
        )
