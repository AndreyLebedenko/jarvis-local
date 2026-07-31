import pytest
from conftest import assert_stdlib_only_imports

from jarvis.history.context_budget import (
    ConservativeUtf8TokenEstimator,
    ContextBudgetError,
    ContextBudgetLimits,
    ContextBudgetRequest,
    PromptEstimateMaterial,
    allocate_context_budget,
)


def test_context_budget_policy_has_no_project_import_dependencies():
    assert_stdlib_only_imports("src/jarvis/history/context_budget.py")


def test_estimator_counts_empty_material_with_fixed_overhead_only():
    estimator = ConservativeUtf8TokenEstimator()

    estimate = estimator.estimate_tokens(
        PromptEstimateMaterial(
            canonical_utf8_bytes=0,
            message_count=0,
            tool_count=0,
        )
    )

    assert estimate == 32


def test_estimator_applies_approved_utf8_formula_to_russian_and_tools():
    estimator = ConservativeUtf8TokenEstimator()
    text = "Привет, запомни: окно контекста должно быть ограничено."

    estimate = estimator.estimate_tokens(
        PromptEstimateMaterial(
            canonical_utf8_bytes=len(text.encode("utf-8")),
            message_count=3,
            tool_count=2,
        )
    )

    assert estimate == 32 + 36 + 48 + ((len(text.encode("utf-8")) + 1) // 2)


def test_context_budget_allocation_accepts_an_exact_fit():
    allocation = allocate_context_budget(
        ContextBudgetLimits(
            prompt_capacity_tokens=100,
            recent_history_max_tokens=30,
            automatic_retrieval_max_tokens=20,
            tool_result_reserve_tokens=10,
            reasoning_generation_reserve_tokens=40,
            estimator_safety_margin_tokens=5,
            minimum_recent_exchanges=1,
        ),
        ContextBudgetRequest(
            fixed_prompt_input_tokens=35,
            recent_history_tokens=30,
            automatic_retrieval_tokens=20,
        ),
    )

    assert allocation.fixed_prompt_input_tokens == 35
    assert allocation.recent_history_tokens == 30
    assert allocation.automatic_retrieval_tokens == 20
    assert allocation.tool_result_reserve_tokens == 10
    assert allocation.reasoning_generation_reserve_tokens == 40
    assert allocation.estimator_safety_margin_tokens == 5
    assert allocation.prompt_input_tokens == 100


def test_context_budget_allocation_accepts_empty_optional_context():
    allocation = allocate_context_budget(
        ContextBudgetLimits(
            prompt_capacity_tokens=64,
            recent_history_max_tokens=16,
            automatic_retrieval_max_tokens=16,
            tool_result_reserve_tokens=8,
            reasoning_generation_reserve_tokens=32,
            estimator_safety_margin_tokens=4,
            minimum_recent_exchanges=1,
        ),
        ContextBudgetRequest(
            fixed_prompt_input_tokens=12,
            recent_history_tokens=0,
            automatic_retrieval_tokens=0,
        ),
    )

    assert allocation.prompt_input_tokens == 24
    assert allocation.available_prompt_tokens == 40


def test_context_budget_allocation_rejects_total_prompt_overflow():
    with pytest.raises(ContextBudgetError, match="prompt budget exceeded"):
        allocate_context_budget(
            ContextBudgetLimits(
                prompt_capacity_tokens=100,
                recent_history_max_tokens=60,
                automatic_retrieval_max_tokens=40,
                tool_result_reserve_tokens=10,
                reasoning_generation_reserve_tokens=40,
                estimator_safety_margin_tokens=5,
                minimum_recent_exchanges=1,
            ),
            ContextBudgetRequest(
                fixed_prompt_input_tokens=46,
                recent_history_tokens=40,
                automatic_retrieval_tokens=0,
            ),
        )


def test_context_budget_allocation_rejects_recent_history_over_its_maximum():
    with pytest.raises(ContextBudgetError, match="recent history"):
        allocate_context_budget(
            ContextBudgetLimits(
                prompt_capacity_tokens=100,
                recent_history_max_tokens=30,
                automatic_retrieval_max_tokens=40,
                tool_result_reserve_tokens=10,
                reasoning_generation_reserve_tokens=40,
                estimator_safety_margin_tokens=5,
                minimum_recent_exchanges=1,
            ),
            ContextBudgetRequest(
                fixed_prompt_input_tokens=10,
                recent_history_tokens=31,
                automatic_retrieval_tokens=0,
            ),
        )


def test_context_budget_allocation_rejects_automatic_retrieval_over_its_maximum():
    with pytest.raises(ContextBudgetError, match="automatic retrieval"):
        allocate_context_budget(
            ContextBudgetLimits(
                prompt_capacity_tokens=100,
                recent_history_max_tokens=30,
                automatic_retrieval_max_tokens=40,
                tool_result_reserve_tokens=10,
                reasoning_generation_reserve_tokens=40,
                estimator_safety_margin_tokens=5,
                minimum_recent_exchanges=1,
            ),
            ContextBudgetRequest(
                fixed_prompt_input_tokens=10,
                recent_history_tokens=0,
                automatic_retrieval_tokens=41,
            ),
        )
