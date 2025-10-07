from __future__ import annotations

from app.services.llm_workflow import ConversationHistory, QueryStrategy


def test_conversation_history_summarises_old_turns() -> None:
    history = ConversationHistory(max_turns=2, summary_token_budget=200)
    history.record_exchange("Q1", "A1")
    history.record_exchange("Q2", "A2")
    history.record_exchange("Q3", "A3")

    retained = list(history.iter_recent_exchanges())
    assert len(retained) == 2
    assert retained[0].question == "Q2"
    assert "Q: Q1" in history.summary


def test_build_answer_messages_adds_summary_and_history() -> None:
    history = ConversationHistory(max_turns=2, summary_token_budget=200)
    history.summary = "Earlier conversation summary"
    history.record_exchange("Why did the container restart?", "It was updated.")

    messages, notices = history.build_answer_messages(
        strategy=QueryStrategy.SUMMARY,
        system_prompt="system prompt",
        question="What should we check next?",
        context_json="{}",
        plan=None,
    )

    assert any(
        message["role"] == "system" and "Conversation summary" in message["content"]
        for message in messages
    )
    assert any(message["role"] == "user" for message in messages)
    assert any(message["role"] == "assistant" for message in messages)
    assert notices, "Summary strategy should record that conversation context was included"


def test_build_plan_messages_include_context() -> None:
    history = ConversationHistory()
    history.record_exchange("Previous question", "Previous answer", plan="Previous plan")

    plan_messages = history.build_plan_messages(
        system_prompt="system", question="Check disk usage", context_json="{\"foo\": \"bar\"}"
    )

    assert plan_messages[0]["role"] == "system"
    assert any(message["role"] == "user" and "Check disk usage" in message["content"] for message in plan_messages)
    assert "{\"foo\": \"bar\"}" in plan_messages[-1]["content"]
