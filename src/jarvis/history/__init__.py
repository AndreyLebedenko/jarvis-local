"""History-domain pure policies and data contracts."""

from jarvis.history.automatic_retrieval import (
    AutomaticRetrievalRequest,
    AutomaticRetrievalSelection,
    AutomaticRetrievalSelectionLimits,
    build_automatic_retrieval_request,
    select_automatic_retrieval_passages,
    to_history_retrieval_query,
)
from jarvis.history.context_budget import (
    CONSERVATIVE_UTF8_ESTIMATOR_FORMULA,
    ConservativeUtf8TokenEstimator,
    ContextBudgetAllocation,
    ContextBudgetError,
    ContextBudgetLimits,
    ContextBudgetRequest,
    PromptEstimateMaterial,
    PromptTokenEstimator,
    allocate_context_budget,
)
from jarvis.history.recent_history import (
    ConversationTurn,
    RecentHistoryExchange,
    RecentHistorySelection,
    estimate_history_contribution_tokens,
    select_recent_history,
    turns_as_messages,
)
from jarvis.history.working_context import (
    RetrievedHistoryPassage,
    WorkingContextAssembly,
    WorkingContextBudget,
    WorkingContextRequest,
    assemble_working_context,
    estimate_working_context_tokens,
    format_retrieved_history_passages,
)

__all__ = [
    "CONSERVATIVE_UTF8_ESTIMATOR_FORMULA",
    "AutomaticRetrievalRequest",
    "AutomaticRetrievalSelection",
    "AutomaticRetrievalSelectionLimits",
    "ConservativeUtf8TokenEstimator",
    "ContextBudgetAllocation",
    "ContextBudgetError",
    "ContextBudgetLimits",
    "ContextBudgetRequest",
    "ConversationTurn",
    "PromptEstimateMaterial",
    "PromptTokenEstimator",
    "RecentHistoryExchange",
    "RecentHistorySelection",
    "RetrievedHistoryPassage",
    "WorkingContextAssembly",
    "WorkingContextBudget",
    "WorkingContextRequest",
    "allocate_context_budget",
    "assemble_working_context",
    "build_automatic_retrieval_request",
    "estimate_history_contribution_tokens",
    "estimate_working_context_tokens",
    "format_retrieved_history_passages",
    "select_automatic_retrieval_passages",
    "select_recent_history",
    "to_history_retrieval_query",
    "turns_as_messages",
]
