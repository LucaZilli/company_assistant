"""Routing orchestrator for company assistant queries."""

from __future__ import annotations

from enum import Enum
import typing as t

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from config import ORCHESTRATOR_MODEL_NAME
from src.shared.knowledge import Document
from src.shared.knowledge import get_doc_summaries_prompt
from src.shared.llm import get_instructor_client
from src.shared.logging import debug_log
from src.shared.safety import get_safety_prompt
from src.shared.usage_tracker import tracker


class ActionType(str, Enum):
    """Available routing actions for the orchestrator."""

    KNOWLEDGE_BASE = 'knowledge_base'
    WEB_SEARCH = 'web_search'
    LLM_ONLY = 'llm_only'
    CLARIFY = 'clarify'
    BLOCKED = 'blocked'


class RoutingDecision(BaseModel):
    """Structured routing decision from the orchestrator."""

    reason: str = Field(description='Brief explanation for the routing decision')
    action: ActionType = Field(
        description=(
            'The action to take: knowledge_base, web_search, llm_only, clarify, '
            'or blocked'
        )
    )
    document: str | None = Field(
        default=None,
        description='Filename to use if action is knowledge_base',
    )
    search_query: str | None = Field(
        default=None,
        description='Search query if action is web_search',
    )
    clarification: str | None = Field(
        default=None,
        description='Question to ask if action is clarify',
    )
    answer_polite_refusal: str | None = Field(
        default=None,
        description='Direct answer if action is `blocked` (polite refusal).',
    )
    answer_general_knowledge: str | None = Field(
        default=None,
        description='Direct answer if action is `llm_only` (general knowledge).',
    )

    @field_validator('action', mode='before')
    @classmethod
    def normalize_action(cls, value: t.Any) -> t.Any:
        """Convert action to lowercase to match enum values.

        Args:
            value: Raw action value from the model.

        Returns:
            Normalized action value.
        """
        if isinstance(value, str):
            return value.lower()
        return value


ROUTING_PROMPT = '''You are a query router for a company assistant.
Decide how to handle user queries.

## Available company documents
{doc_summaries}

## Safety guidelines
{safety_guidelines}

## Routing rules
1. KNOWLEDGE_BASE: For company-specific info (policies, procedures, coding style).
   Set `document` to the exact filename.
2. WEB_SEARCH: For current/external info (news, facts, tools). Set `search_query`
   to an optimized query. In particular generate this routing class for latest
   news and queries whose answer can change over time.
3. LLM_ONLY: For general knowledge you can answer directly. In particular,
   generate this routing class if the knowledge does not change over time and
   you know it. Then generate `answer_general_knowledge`.
4. CLARIFY: If query is ambiguous or very general. Set `clarification` to your
   question. In particular if the user ask question about the knowledge base of
   the company must not be too general.
5. BLOCKED: If query is harmful. Set `answer` to a polite refusal in the user's
   language. Then generate `answer_polite_refusal`.

Prefer KNOWLEDGE_BASE for anything about ZURU Melon company. Remember to answer in in user's language.'''


def route_query(
    query: str,
    documents: dict[str, Document],
    conversation_history: list[dict[str, str]] | None = None,
) -> RoutingDecision:
    """Determine how to handle a user query using structured output.

    Args:
        query: User question to route.
        documents: Knowledge base documents.
        conversation_history: Recent conversation messages for context.

    Returns:
        A structured routing decision.
    """
    client = get_instructor_client()

    doc_summaries = get_doc_summaries_prompt(documents)
    safety_guidelines = get_safety_prompt()
    system_prompt = ROUTING_PROMPT.format(
        doc_summaries=doc_summaries,
        safety_guidelines=safety_guidelines,
    )

    if conversation_history:
        history_text = '\n'.join(
            [
                f"{'User' if i % 2 == 0 else 'Assistant'}: {msg.get('content', '')}"
                for i, msg in enumerate(conversation_history[-8:])# maximum 8 messages in memory 
            ]
        )
        user_content = f'Recent conversation:\n{history_text}\n\nCurrent query: {query}'
    else:
        user_content = f'Query: {query}'

    debug_log('ROUTER INPUT - System Prompt', system_prompt, style='yellow')
    debug_log('ROUTER INPUT - User Content', user_content, style='yellow')

    response = client.chat.completions.create_with_completion(
        model=ORCHESTRATOR_MODEL_NAME,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_content},
        ],
        response_model=RoutingDecision,
        max_retries=3,
    )

    decision, completion = response

    usage = tracker.add_from_instructor(completion, ORCHESTRATOR_MODEL_NAME, 'routing')

    debug_log(
        'ROUTER - Token Usage',
        (
            f'Input: {usage.input_tokens} | Output: {usage.output_tokens} | '
            f'Cost: ${usage.calculate_cost():.6f}'
        ),
        style='dim',
    )

    debug_log(
        'ROUTER OUTPUT - Decision',
        (
            f'Action: {decision.action.value}\n'
            f'Reason: {decision.reason}\n'
            f'Document: {decision.document}\n'
            f'Search Query: {decision.search_query}\n'
            f'Clarification: {decision.clarification}\n'
            f'Answer (refusal): {decision.answer_polite_refusal}'
            f'Answer (knowledge base): {decision.answer_general_knowledge}'
        ),
        style='green',
    )

    return decision
