from __future__ import annotations

from duckduckgo_search import DDGS
from openai import OpenAIError
import requests

from config import SEARCH_MODEL_NAME
from config import SERPER_API_KEY
from src.shared.llm import get_llm
from src.shared.logging import debug_log
from src.shared.usage_tracker import TokenUsage
from src.shared.usage_tracker import tracker


def web_search_with_perplexity(query: str) -> str:
    """Search the web using the Perplexity model.

    Args:
        query: User query to search for.

    Returns:
        A summarized response string or an error message.
    """
    try:
        llm = get_llm(SEARCH_MODEL_NAME)
        messages = [
            {
                'role': 'system',
                'content': (
                    'You are a helpful search assistant. Provide accurate, up-to-date '
                    'information with sources when available. Be concise but complete.'
                ),
            },
            {'role': 'user', 'content': query},
        ]
        debug_log('SEARCH INPUT', f'Query: {query}', style='magenta')
        response = llm.invoke(messages)
        usage = tracker.add_from_openai(
            response.completion,
            model=SEARCH_MODEL_NAME,
            call_type='search',
        )
        debug_log(
            'SEARCH - Token Usage',
            (
                f'Input: {usage.input_tokens} | Output: {usage.output_tokens} | '
                f'Cost: ${usage.calculate_cost():.6f}'
            ),
            style='dim',
        )
        debug_log('SEARCH OUTPUT', response.content, style='blue')
        return response.content
    except (OpenAIError, RuntimeError, ValueError) as exc:
        return f'Search error: {exc}'


def web_search_with_duck(query: str, max_results: int = 5) -> str:
    """Search DuckDuckGo and return cleaned results.

    Args:
        query: Query string to search for.
        max_results: Maximum number of results to return.

    Returns:
        A formatted string with deduplicated results or an error message.
    """
    try:
        with DDGS() as ddgs:
            results = list(
                ddgs.text(
                    query,
                    max_results=max_results * 2,
                    safesearch='moderate',
                    timelimit='y',
                    region='it-it',
                )
            )

        if not results:
            return 'No relevant results found.'

        seen_urls: set[str] = set()
        cleaned: list[dict[str, str]] = []

        for result in results:
            url = result.get('href')
            body = result.get('body', '').strip()
            title = result.get('title', '').strip()

            if not url or not body or url in seen_urls:
                continue

            seen_urls.add(url)

            cleaned.append({'title': title, 'snippet': body, 'url': url})

            if len(cleaned) >= max_results:
                break

        if not cleaned:
            return 'No high-quality results after filtering.'

        output: list[str] = []
        for index, result in enumerate(cleaned, 1):
            output.append(
                f"{index}. {result['title']}\n"
                f"{result['snippet']}\n"
                f"Source: {result['url']}\n"
            )

        return '\n'.join(output)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        return f'Search error: {exc}'


def web_search_with_serper(query: str, num_results: int = 5) -> str:
    """Search the web using the Serper.dev Google Search API.

    Args:
        query: Query string to search for.
        num_results: Maximum number of results to return.

    Returns:
        A formatted string with results or an error message.
    """
    if not SERPER_API_KEY:
        return 'Error: SERPER_API_KEY not set'

    url = 'https://google.serper.dev/search'
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json',
    }
    payload = {'q': query, 'num': num_results}

    try:
        debug_log('SEARCH INPUT', f'Serper query: {query}', style='magenta')
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()

        usage = tracker.add(
            TokenUsage(
                input_tokens=0,
                output_tokens=0,
                model='serper',
                call_type='search',
            )
        )

        debug_log(
            'SEARCH - Token Usage',
            (
                f'Input: {usage.input_tokens} | Output: {usage.output_tokens} | '
                f'Cost: ${usage.calculate_cost():.6f}'
            ),
            style='dim',
        )

        data = response.json()
        results: list[str] = []

        organic = data.get('organic', [])
        for index, result in enumerate(organic[:num_results], 1):
            title = result.get('title', 'No title')
            snippet = result.get('snippet', 'No snippet')
            link = result.get('link', 'No URL')
            results.append(f'{index}. {title}\n   {snippet}\n   {link}\n')

        if not results:
            return 'No results found.'

        output = '\n'.join(results)
        debug_log('SEARCH OUTPUT', output, style='blue')
        return output
    except requests.RequestException as exc:
        return f'Serper search error: {exc}'
