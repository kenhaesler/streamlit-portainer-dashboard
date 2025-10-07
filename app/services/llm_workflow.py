"""Utilities for managing LLM chat workflows inside the dashboard."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Iterator, Mapping

__all__ = [
    "ConversationExchange",
    "ConversationHistory",
    "QueryStrategy",
]


class QueryStrategy(str, Enum):
    """Supported chat orchestration strategies."""

    DIRECT = "direct"
    SUMMARY = "summary"
    STAGED = "staged"
    DYNAMIC = "dynamic"


@dataclass(slots=True)
class ConversationExchange:
    """Represents a single question/answer pair with optional analysis plan."""

    question: str
    answer: str
    plan: str | None = None


def _truncate_to_budget(text: str, token_budget: int) -> str:
    """Trim *text* so that it stays within the approximate *token_budget*."""

    if token_budget <= 0 or not text:
        return ""
    approx_char_budget = token_budget * 4
    if len(text) <= approx_char_budget:
        return text
    truncated = text[:approx_char_budget].rstrip()
    if not truncated:
        return ""
    return truncated + "\n…"


@dataclass
class ConversationHistory:
    """Stores recent exchanges and maintains a running summary of older turns."""

    max_turns: int = 3
    summary_token_budget: int = 600
    exchanges: list[ConversationExchange] = field(default_factory=list)
    summary: str = ""

    def configure(self, *, max_turns: int, summary_token_budget: int) -> None:
        """Update retention limits and enforce them immediately."""

        if max_turns < 1:
            max_turns = 1
        self.max_turns = max_turns
        if summary_token_budget < 0:
            summary_token_budget = 0
        self.summary_token_budget = summary_token_budget
        self._enforce_limits()

    def record_exchange(
        self,
        question: str,
        answer: str,
        *,
        plan: str | None = None,
    ) -> None:
        """Add a new interaction and summarise if the window would overflow."""

        self.exchanges.append(ConversationExchange(question=question, answer=answer, plan=plan))
        self._enforce_limits()

    def iter_recent_exchanges(self) -> Iterator[ConversationExchange]:
        """Yield retained exchanges from oldest to newest."""

        return iter(self.exchanges)

    def build_answer_messages(
        self,
        *,
        strategy: QueryStrategy,
        system_prompt: str,
        question: str,
        context_json: str,
        plan: str | None = None,
    ) -> tuple[list[Mapping[str, str]], list[str]]:
        """Construct chat messages for the answer phase."""

        notices: list[str] = []
        messages: list[Mapping[str, str]] = [{"role": "system", "content": system_prompt}]

        if plan:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Use the following analysis plan when answering.\n"
                        f"{plan.strip()}"
                    ),
                }
            )

        if strategy in (
            QueryStrategy.SUMMARY,
            QueryStrategy.STAGED,
            QueryStrategy.DYNAMIC,
        ):
            if self.summary:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Conversation summary of earlier turns:\n"
                            f"{self.summary.strip()}"
                        ),
                    }
                )
                notices.append("Included condensed conversation history in the prompt.")
            for exchange in self.exchanges:
                messages.extend(
                    [
                        {
                            "role": "user",
                            "content": f"Earlier question: {exchange.question.strip()}",
                        },
                        {
                            "role": "assistant",
                            "content": f"Earlier answer: {exchange.answer.strip()}",
                        },
                    ]
                )
                if exchange.plan:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": (
                                "Analysis plan used for the previous answer:\n"
                                f"{exchange.plan.strip()}"
                            ),
                        }
                    )

        messages.append(
            {
                "role": "user",
                "content": (
                    f"Question: {question.strip()}\n\nContext (JSON):\n{context_json}"
                ),
            }
        )
        return messages, notices

    def build_plan_messages(
        self,
        *,
        system_prompt: str,
        question: str,
        context_json: str,
    ) -> list[Mapping[str, str]]:
        """Create a planning prompt that keeps the request concise."""

        messages: list[Mapping[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are an operations assistant that prepares concise analysis plans "
                    "for another assistant. Focus on highlighting the specific Portainer "
                    "metrics the second assistant should inspect."
                ),
            }
        ]
        if self.summary:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Conversation summary so far:\n"
                        f"{self.summary.strip()}"
                    ),
                }
            )
        for exchange in self.exchanges:
            messages.extend(
                [
                    {
                        "role": "user",
                        "content": f"Earlier question: {exchange.question.strip()}",
                    },
                    {
                        "role": "assistant",
                        "content": f"Earlier answer: {exchange.answer.strip()}",
                    },
                ]
            )
        messages.append(
            {
                "role": "user",
                "content": (
                    "Draft a short bullet list describing how to answer the following question. "
                    "Call out the most relevant tables, environments, or metrics from the "
                    "provided context so the answering assistant can stay within the token budget.\n\n"
                    f"Question: {question.strip()}\n\nContext (JSON):\n{context_json}"
                ),
            }
        )
        return messages

    def build_catalog_messages(
        self,
        *,
        system_prompt: str,
        question: str,
        catalog_json: str,
    ) -> list[Mapping[str, str]]:
        """Create a prompt asking which context tables the model needs."""

        messages: list[Mapping[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a planning assistant that chooses the smallest Portainer context needed "
                    "for another assistant to answer the operator's question."
                ),
            },
            {"role": "system", "content": system_prompt},
        ]
        if self.summary:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Conversation summary so far:\n"
                        f"{self.summary.strip()}"
                    ),
                }
            )
        for exchange in self.exchanges:
            messages.extend(
                [
                    {
                        "role": "user",
                        "content": f"Earlier question: {exchange.question.strip()}",
                    },
                    {
                        "role": "assistant",
                        "content": f"Earlier answer: {exchange.answer.strip()}",
                    },
                ]
            )
        user_content = (
            f"Question: {question.strip()}\n\nAvailable context catalog (JSON):\n{catalog_json}\n\n"
            "Respond with compact JSON in this shape: "
            "{{\"tables\": [{{\"name\": \"containers\", \"limit\": 40, \"filters\": {{\"environment_name\": [\"prod\"]}}}}], "
            "\"include_summary\": true}}. Pick table names from the catalog only, prefer narrow filters "
            "(environment, stack, status), and keep limits small so the prompt stays short. If no tables are "
            "required reply with {{\"tables\": []}}."
        )
        messages.append({"role": "user", "content": user_content})
        return messages

    def to_state(self) -> dict[str, object]:
        """Serialise the history for storage in ``st.session_state``."""

        return {
            "max_turns": self.max_turns,
            "summary_token_budget": self.summary_token_budget,
            "summary": self.summary,
            "exchanges": [
                {
                    "question": exchange.question,
                    "answer": exchange.answer,
                    "plan": exchange.plan,
                }
                for exchange in self.exchanges
            ],
        }

    @classmethod
    def from_state(cls, state: Mapping[str, object] | None) -> "ConversationHistory":
        """Restore a history instance from ``st.session_state`` data."""

        history = cls()
        if not state:
            return history
        history.max_turns = int(state.get("max_turns", history.max_turns))
        history.summary_token_budget = int(
            state.get("summary_token_budget", history.summary_token_budget)
        )
        history.summary = str(state.get("summary", ""))
        exchanges_state = state.get("exchanges", [])
        if isinstance(exchanges_state, Iterable):
            for item in exchanges_state:
                if not isinstance(item, Mapping):
                    continue
                history.exchanges.append(
                    ConversationExchange(
                        question=str(item.get("question", "")),
                        answer=str(item.get("answer", "")),
                        plan=str(item.get("plan")) if item.get("plan") is not None else None,
                    )
                )
        history._enforce_limits()
        return history

    def _enforce_limits(self) -> None:
        """Ensure the retained window and summary respect current limits."""

        while len(self.exchanges) > self.max_turns:
            removed = self.exchanges.pop(0)
            snippet = self._format_summary_snippet(removed)
            if snippet:
                if self.summary:
                    self.summary += "\n"
                self.summary += snippet
                self.summary = _truncate_to_budget(self.summary, self.summary_token_budget)

        if self.summary_token_budget <= 0:
            self.summary = ""
        else:
            self.summary = _truncate_to_budget(self.summary, self.summary_token_budget)

    @staticmethod
    def _format_summary_snippet(exchange: ConversationExchange) -> str:
        question = exchange.question.strip()
        answer = exchange.answer.strip()
        plan = (exchange.plan or "").strip()
        parts = [
            f"Q: {question}" if question else "",
            f"A: {answer}" if answer else "",
            f"Plan: {plan}" if plan else "",
        ]
        filtered = [part for part in parts if part]
        return " \u2013 ".join(filtered)

