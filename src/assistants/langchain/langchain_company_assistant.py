from __future__ import annotations

import typing as t

from langchain_classic.agents import AgentType
from langchain_classic.agents import initialize_agent
from langchain_classic.memory import ConversationBufferWindowMemory
from langchain_community.callbacks.manager import get_openai_callback
from langchain_openai import ChatOpenAI
from langchain.tools import tool

from config import GENERATOR_MODEL_NAME
from config import OPENROUTER_API_KEY
from config import OPENROUTER_BASE_URL
from src.shared.cache import CachedResponse
from src.shared.cache import QueryCache
from src.shared.cache import get_cache
from src.shared.knowledge import Document
from src.shared.knowledge import get_doc_summaries_prompt
from src.shared.knowledge import load_documents
from src.shared.logging import debug_log
from src.shared.safety import get_safety_prompt
from src.shared.usage_tracker import TokenUsage
from src.shared.usage_tracker import tracker
from src.shared.web_search import web_search_with_perplexity
import warnings
from langchain_core._api.deprecation import LangChainDeprecationWarning

warnings.filterwarnings('ignore', category=LangChainDeprecationWarning) # just to remove an annoying warning



SYSTEM_PROMPT = '''You are an autonomous assistant of a company named ZURU.
Employees can use you to ask general questions.
Use tools when needed.

# Available company documents
{doc_summaries}

# Safety guidelines
{safety_guidelines}

# Rules
1. For company-specific info (policies, procedures, coding style),
   use kb_search with the exact filename as the query.
2. For current/external info (news, facts), use the web_search tool
   and generate an optimized query, especially for latest news and
   queries whose answers can change over time.
3. For general knowledge, answer directly without calling any tool when the answer does not
   change over time and you know it.
4. If the query is ambiguous or very general, ask a clarifying question.
5. If the query is harmful, politely refuse to answer.
6. If you do not find the answer you want using the tool you chose, reason about
   whether you can call the same tool again with another input or call another tool.
7. Remember to answer in the user's language.
'''


class LangChainCompanyAssistant:
    """Company assistant backed by a LangChain agent and windowed memory."""

    def __init__(self, debug: bool = False, use_cache: bool | None = None) -> None:
        """Initialize the assistant.

        Args:
            debug: If True, enable verbose agent logging.
            use_cache: Whether to enable Postgres-backed caching.
        """
        self.documents: dict[str, Document] = load_documents()
        self.use_cache = use_cache
        self._cache: QueryCache | None = None

        self.model = ChatOpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            model=GENERATOR_MODEL_NAME,
            temperature=0.0,
            max_tokens=1024,
        )

        self.memory = ConversationBufferWindowMemory(
            k=8,
            memory_key='chat_history',
            return_messages=True,
            input_key='input',
            output_key='output',
        )

        self._agent: t.Any | None = None
        self.debug = debug

    @property
    def cache(self) -> QueryCache | None:
        """Return a lazy-initialized cache instance.

        Returns:
            A QueryCache instance if enabled, otherwise None.
        """
        if self._cache is None and self.use_cache:
            try:
                self._cache = get_cache(agent_type='langchain')
            except Exception as exc:
                debug_log('CACHE', f'Cache unavailable: {exc}', style='yellow')
                self.use_cache = False
        return self._cache

    @property
    def agent(self) -> t.Any:
        """Return the cached LangChain agent, building it when needed.

        Returns:
            The initialized LangChain agent.
        """
        if self._agent is not None:
            return self._agent

        @tool
        def kb_search(query: str) -> str:
            """Search ZURU internal documents by filename or keyword.

            Args:
                query: Exact filename or short, specific keywords.

            Returns:
                Raw document content if found; otherwise a fallback message.
            """
            q = query.lower()
            doc = self.documents.get(q)
            return (
                doc.content
                if doc
                else 'No document found, call the tool again with a correct query.'
            )

        @tool
        def web_search(query: str) -> str:
            """Search the public web for current or external information.

            Args:
                query: Concise, optimized web search query.

            Returns:
                Summarized web results or relevant snippets.
            """
            return web_search_with_perplexity(query)

        doc_summaries = get_doc_summaries_prompt(self.documents)
        safety_guidelines = get_safety_prompt()
        system_prompt = SYSTEM_PROMPT.format(
            doc_summaries=doc_summaries,
            safety_guidelines=safety_guidelines,
        )
        self._agent = initialize_agent(
            tools=[kb_search, web_search],
            llm=self.model,
            agent=AgentType.CHAT_CONVERSATIONAL_REACT_DESCRIPTION,
            agent_kwargs={'system_message': system_prompt},
            memory=self.memory,
            verbose=self.debug,
        )
        return self._agent

    def process_query(self, query: str) -> str:
        """Run the agent for a single user query.

        Args:
            query: The user message to process.

        Returns:
            The assistant response text.
        """
        cached = self._check_cache(query)
        if cached:
            self._save_cached_to_memory(query, cached.response)
            return cached.response

        debug_log('LANGCHAIN INPUT', f'Query: {query}', style='magenta')
        messages = self.memory.chat_memory.messages
        formatted = '\n'.join(
            f'{msg.type}: {msg.content}' for msg in messages if msg is not None
        )
        debug_log('LANGCHAIN INPUT', f'Conversation memory before input:\n{formatted}', style='magenta')
        with get_openai_callback() as cb:
            result = self.agent.invoke({'input': query})

        in_tok = cb.prompt_tokens
        out_tok = cb.completion_tokens
        if in_tok or out_tok:
            usage = tracker.add(
                TokenUsage(
                    in_tok,
                    out_tok,
                    GENERATOR_MODEL_NAME,
                    'generation',
                )
            )
            debug_log(
                'GENERATOR - Token Usage',
                (
                    f'Input: {usage.input_tokens} | Output: {usage.output_tokens} | '
                    f'Cost: ${usage.calculate_cost():.6f}'
                ),
                style='dim',
            )

        response = result.get('output', '')
        self._save_to_cache(query, response)
        debug_log('LANGCHAIN OUTPUT', response, style='blue')
        return response

    def reset(self) -> None:
        """Reset the conversation memory."""
        self.memory.clear()

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
                    f'Found cached response (hits: {cached.hit_count})',
                    style='green',
                )
            return cached
        except Exception as exc:
            debug_log('CACHE', f'Cache lookup error: {exc}', style='yellow')
            return None

    def _save_to_cache(self, query: str, response: str) -> None:
        """Save a response to cache when appropriate.

        Args:
            query: User query to cache.
            response: Response text.
        """
        if not self.use_cache or not self.cache:
            return

        try:
            self.cache.set(query, response, routing_action=None)
            debug_log('CACHE', 'Saved to cache (agent: langchain)', style='green')
        except Exception as exc:
            debug_log('CACHE', f'Cache save error: {exc}', style='yellow')

    def _save_cached_to_memory(self, query: str, response: str) -> None:
        """Record a cached exchange in the conversation memory.

        Args:
            query: User query that produced the cached response.
            response: Cached response text.
        """
        try:
            self.memory.save_context({'input': query}, {'output': response})
        except Exception as exc:
            debug_log('CACHE', f'Cache history save error: {exc}', style='yellow')
