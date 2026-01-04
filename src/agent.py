"""Core company assistant logic for routing and response generation."""

from __future__ import annotations

import typing as t

from config import GENERATOR_MODEL_NAME
from .cache import CachedResponse
from .cache import QueryCache
from .cache import get_cache
from .knowledge import Document
from .knowledge import load_documents
from .llm import get_llm
from .orchestrator import ActionType
from .orchestrator import RoutingDecision
from .orchestrator import debug_log
from .orchestrator import route_query
from .safety import get_safety_prompt
from .usage_tracker import tracker
from .web_search import web_search_with_perplexity


RESPONSE_PROMPT = '''You are a helpful company assistant for ZURU, an AI solutions company.
Answer the user's question based on the provided context. Be concise but complete.
If the context doesn't contain enough information, say so.
Always maintain a professional and friendly tone.
'''


class CompanyAssistant:
    """Assistant that routes queries and composes responses."""

    def __init__(self, use_cache: bool | None = None) -> None:
        """Initialize the assistant.

        Args:
            use_cache: Whether to enable cached responses.
        """
        self.documents: dict[str, Document] = load_documents()
        self.llm = get_llm(GENERATOR_MODEL_NAME, temperature=0.3)
        self.conversation_history: list[dict[str, str]] = []
        self.use_cache = use_cache
        self._cache: QueryCache | None = None

    @property
    def cache(self) -> QueryCache | None:
        """Return a lazy-initialized cache instance.

        Returns:
            A QueryCache instance if enabled, otherwise None.
        """
        if self._cache is None and self.use_cache:
            try:
                self._cache = get_cache()
            except Exception as exc:
                debug_log('CACHE', f'Cache unavailable: {exc}', style='yellow')
                self.use_cache = False
        return self._cache

    def _generate_response(self, query: str, context: str) -> str:
        """Generate a response using the LLM with provided context.

        Args:
            query: User query to answer.
            context: Context string to include in the prompt.

        Returns:
            The assistant response.
        """
        system_prompt = RESPONSE_PROMPT.format(safety_guidelines=get_safety_prompt())

        messages: list[dict[str, str]] = [
            {'role': 'system', 'content': system_prompt},
        ]

        for msg in self.conversation_history[-4:]:
            messages.append(msg)

        if context:
            user_message = f'Context:\n{context}\n\nUser question: {query}'
        else:
            user_message = query
        messages.append({'role': 'user', 'content': user_message})

        debug_log('GENERATOR INPUT - System Prompt', system_prompt, style='magenta')

        if self.conversation_history:
            history_str = '\n'.join(
                [
                    f"- {msg.get('content', '')[:100]}..."
                    for msg in self.conversation_history[-4:]
                ]
            )
            debug_log(
                'GENERATOR INPUT - Conversation History',
                history_str,
                style='magenta',
            )

        if len(context) < 2000:
            context_display = context
        else:
            context_display = (
                f'{context[:1000]}\n\n[... truncated {len(context)} chars ...]\n\n'
                f'{context[-500:]}'
            )

        debug_log(
            'GENERATOR INPUT - Context + Query',
            (
                f'Context length: {len(context)} chars\n\n{context_display}\n\n---\n'
                f'Query: {query}'
            ),
            style='magenta',
        )

        response = self.llm.invoke(messages)
        usage = tracker.add_from_openai(response.completion, GENERATOR_MODEL_NAME, 'generation')

        debug_log(
            'GENERATOR - Token Usage',
            (
                f'Input: {usage.input_tokens} | Output: {usage.output_tokens} | '
                f'Cost: ${usage.calculate_cost():.6f}'
            ),
            style='dim',
        )

        debug_log('GENERATOR OUTPUT - LLM Response', response.content, style='blue')

        return response.content

    def _check_cache(self, query: str) -> CachedResponse | None:
        """Check if a query exists in cache.

        Args:
            query: User query to look up.

        Returns:
            CachedResponse if found, otherwise None.
        """
        if not self.use_cache or not self.cache:
            return None

        try:
            cached = self.cache.get(query)
            if cached:
                debug_log(
                    'CACHE HIT',
                    (
                        f'Found cached response (hits: {cached.hit_count})\n'
                        f'Routing: {cached.routing_action}'
                    ),
                    style='green',
                )
            return cached
        except Exception as exc:
            debug_log('CACHE', f'Cache lookup error: {exc}', style='yellow')
            return None

    def _save_to_cache(self, query: str, response: str, routing_action: str) -> None:
        """Save a response to cache when appropriate.

        Args:
            query: User query to cache.
            response: Response text.
            routing_action: Routing action associated with the response.
        """
        if not self.use_cache or not self.cache:
            return

        non_cacheable_actions = {ActionType.WEB_SEARCH.value}
        if routing_action in non_cacheable_actions:
            debug_log('CACHE', f'Not caching {routing_action} (dynamic content)', style='dim')
            return

        try:
            self.cache.set(query, response, routing_action)
            debug_log('CACHE', f'Saved to cache (action: {routing_action})', style='green')
        except Exception as exc:
            debug_log('CACHE', f'Cache save error: {exc}', style='yellow')

    def process_query(self, query: str) -> tuple[str, RoutingDecision]:
        """Process a user query and return the response and routing decision.

        Args:
            query: User query to process.

        Returns:
            A tuple of response text and routing decision.
        """
        cached = self._check_cache(query)
        if cached:
            decision = RoutingDecision(
                reason='Retrieved from cache',
                action=ActionType(cached.routing_action),
            )
            response = cached.response
            self.conversation_history.append({'role': 'user', 'content': query})
            self.conversation_history.append({'role': 'assistant', 'content': response})
            return response, decision

        decision = route_query(query, self.documents, self.conversation_history)

        if decision.action == ActionType.BLOCKED:
            response = decision.answer or 'I cannot help with that request.'
            debug_log('BLOCKED', f'Query blocked: {decision.reason}', style='red')
        elif decision.action == ActionType.KNOWLEDGE_BASE:
            doc = self.documents.get(decision.document)
            if doc:
                context = f'From {doc.name}:\n\n{doc.content}'
                debug_log(
                    'KNOWLEDGE BASE - Document Loaded',
                    f'File: {decision.document}\nSize: {len(doc.content)} chars',
                    style='cyan',
                )
                response = self._generate_response(query, context)
            else:
                response = (
                    f"Document '{decision.document}' not found. "
                    f'Available: {list(self.documents.keys())}'
                )
                debug_log('KNOWLEDGE BASE - Error', response, style='red')
        elif decision.action == ActionType.WEB_SEARCH:
            debug_log(
                'WEB SEARCH - Query',
                f'Searching for: {decision.search_query or query}',
                style='cyan',
            )
            search_results = web_search_with_perplexity(decision.search_query or query)

            debug_log(
                'WEB SEARCH - Results',
                search_results[:1500] + ('...' if len(search_results) > 1500 else ''),
                style='cyan',
            )
            context = (
                f"Web search results for '{decision.search_query}':\n\n{search_results}"
            )
            response = self._generate_response(query, context)
        elif decision.action == ActionType.CLARIFY:
            response = decision.clarification
            debug_log('CLARIFY', f'Asking: {response}', style='yellow')
        else:
            debug_log('LLM ONLY', 'No external context needed', style='cyan')
            response = self._generate_response(query, '')

        self._save_to_cache(query, response, decision.action.value)
        self.conversation_history.append({'role': 'user', 'content': query})
        self.conversation_history.append({'role': 'assistant', 'content': response})

        return response, decision

    def reset(self) -> None:
        """Reset conversation history."""
        self.conversation_history = []

    def cache_stats(self) -> dict[str, t.Any]:
        """Return cache statistics.

        Returns:
            Cache statistics or an empty dictionary.
        """
        if self.cache:
            return self.cache.stats()
        return {}
