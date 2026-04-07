"""State machine primitives for planned code-evaluator jobs."""

from __future__ import annotations

from enum import Enum

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    class StrEnum(str, Enum):
        pass


class CodeEvalJobState(StrEnum):
    """Lifecycle states for code evaluation execution."""

    QUEUED = "QUEUED"
    EXECUTING_RAW = "EXECUTING_RAW"
    AI_ANALYZING = "AI_ANALYZING"
    RETRYING_SHIM = "RETRYING_SHIM"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


_ALLOWED_TRANSITIONS: dict[CodeEvalJobState, set[CodeEvalJobState]] = {
    CodeEvalJobState.QUEUED: {
        CodeEvalJobState.EXECUTING_RAW,
        CodeEvalJobState.FAILED,
    },
    CodeEvalJobState.EXECUTING_RAW: {
        CodeEvalJobState.AI_ANALYZING,
        CodeEvalJobState.FINALIZING,
        CodeEvalJobState.FAILED,
    },
    CodeEvalJobState.AI_ANALYZING: {
        CodeEvalJobState.RETRYING_SHIM,
        CodeEvalJobState.FAILED,
    },
    CodeEvalJobState.RETRYING_SHIM: {
        CodeEvalJobState.FINALIZING,
        CodeEvalJobState.FAILED,
    },
    CodeEvalJobState.FINALIZING: {
        CodeEvalJobState.COMPLETED,
        CodeEvalJobState.FAILED,
    },
    CodeEvalJobState.COMPLETED: set(),
    CodeEvalJobState.FAILED: set(),
}


def can_transition(current: CodeEvalJobState, nxt: CodeEvalJobState) -> bool:
    """Return True when the transition is valid for the evaluator lifecycle."""
    return nxt in _ALLOWED_TRANSITIONS[current]


def validate_transition(current: CodeEvalJobState, nxt: CodeEvalJobState) -> None:
    """Validate a state transition and raise ValueError when invalid."""
    if can_transition(current, nxt):
        return
    allowed = ", ".join(sorted(s.value for s in _ALLOWED_TRANSITIONS[current])) or "<none>"
    raise ValueError(
        f"Invalid code-eval state transition: {current.value} -> {nxt.value}. "
        f"Allowed next states: {allowed}."
    )


def default_initial_state() -> CodeEvalJobState:
    """Default initial state for newly created code-eval jobs."""
    return CodeEvalJobState.QUEUED
