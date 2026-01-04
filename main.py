from __future__ import annotations

import traceback
import typing as t

import psycopg
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from config import CACHE_ENABLED
from src.assistants.classic.agent import CompanyAssistant
from src.assistants.langchain.langchain_company_assistant import LangChainCompanyAssistant
from src.migrations import MigrationManager
from src.shared.knowledge import load_documents
from src.shared.logging import set_debug_mode

app = typer.Typer(help='ZURU Company Assistant')
console = Console()


def print_welcome(debug: bool = False) -> None:
    """Print the welcome message.

    Args:
        debug: Whether debug mode is enabled.
    """
    debug_note = '\n[DEBUG MODE ENABLED - showing all LLM inputs/outputs]' if debug else ''
    welcome_text = f'''
# ZURU Company Assistant

Welcome! I can help you with:
- **Company policies** and procedures
- **Coding style** guidelines
- **General questions** (using web search or my knowledge)

Type your question, or use these commands:
- `quit` / `exit` - Exit the assistant
- `reset` - Clear conversation history
- `docs` - List available documents
- `cache` - Show cache statistics
- `cache clear` - Clear the cache{debug_note}
'''
    console.print(Panel(Markdown(welcome_text), border_style='green'))


def print_cache_stats(stats: dict[str, t.Any]) -> None:
    """Print cache statistics in a table.

    Args:
        stats: Cache statistics dictionary.
    """
    if not stats or stats.get('total_entries') is None:
        console.print('[yellow]Cache is empty or unavailable[/yellow]')
        return

    table = Table(title='📦 Cache Statistics')
    table.add_column('Metric', style='cyan')
    table.add_column('Value', style='green')

    table.add_row('Total entries', str(stats.get('total_entries', 0)))
    table.add_row('Valid entries (within TTL)', str(stats.get('valid_entries', 0)))
    table.add_row('TTL (days)', str(stats.get('ttl_days', 'N/A')))
    table.add_row('Total hits', str(stats.get('total_hits', 0)))

    avg_hits = stats.get('avg_hits_per_entry') or 0
    table.add_row('Avg hits/entry', f'{avg_hits:.1f}')

    table.add_row('Oldest entry', str(stats.get('oldest_entry', 'N/A')))
    table.add_row('Most recent use', str(stats.get('most_recent_use', 'N/A')))

    console.print(table)


@app.command()
def chat(
    debug: bool = typer.Option(
        False,
        '--debug',
        '-d',
        help='Show ALL LLM inputs/outputs',
    ),
) -> None:
    """Start interactive chat with the classic assistant.

    Args:
        debug: Whether to enable debug logging.
    """
    set_debug_mode(debug)

    documents = load_documents()
    if not documents:
        console.print('[yellow]⚠️  No documents found in knowledge_base/[/yellow]')
        console.print('[dim]Create the folder and add your .md files[/dim]')
    else:
        console.print(f'[green]✓ Loaded {len(documents)} documents[/green]')

    assistant = CompanyAssistant(use_cache=CACHE_ENABLED)

    if CACHE_ENABLED:
        try:
            stats = assistant.cache_stats()
            if stats:
                total_entries = stats.get('total_entries', 0)
                console.print(f'[green]✓ Cache connected ({total_entries} entries)[/green]')
        except (OSError, RuntimeError, ValueError, psycopg.Error) as exc:
            console.print(f'[yellow]⚠️  Cache unavailable: {exc}[/yellow]')

    print_welcome(debug)

    while True:
        try:
            query = console.input('\n[bold blue]You:[/bold blue] ').strip()

            if not query:
                continue

            query_lower = query.lower()

            if query_lower in ('quit', 'exit'):
                console.print('[green]Goodbye! 👋[/green]')
                break

            if query_lower == 'reset':
                assistant.reset()
                console.print('[yellow]Conversation reset.[/yellow]')
                continue

            if query_lower == 'docs':
                if assistant.documents:
                    console.print('\n[bold]Available documents:[/bold]')
                    for filename, doc in assistant.documents.items():
                        console.print(f'  • {filename}: {doc.summary}')
                else:
                    console.print('[yellow]No documents loaded.[/yellow]')
                continue

            if query_lower == 'cache':
                print_cache_stats(assistant.cache_stats())
                continue

            if query_lower == 'cache clear':
                if assistant.cache:
                    deleted = assistant.cache.clear()
                    console.print(f'[yellow]Cache cleared ({deleted} entries removed)[/yellow]')
                else:
                    console.print('[yellow]Cache not available[/yellow]')
                continue

            if query_lower == 'debug on':
                set_debug_mode(True)
                console.print('[yellow]Debug mode enabled[/yellow]')
                continue

            if query_lower == 'debug off':
                set_debug_mode(False)
                console.print('[yellow]Debug mode disabled[/yellow]')
                continue

            if debug:
                response, _decision = assistant.process_query(query)
            else:
                with console.status('[bold green]Thinking...'):
                    response, _decision = assistant.process_query(query)

            console.print(f'\n[bold green]Assistant:[/bold green] {response}')

        except KeyboardInterrupt:
            console.print('\n[green]Goodbye! 👋[/green]')
            break
        except Exception as exc:
            console.print(f'[red]Error: {exc}[/red]')
            if debug:
                console.print(traceback.format_exc())


@app.command(name='chat-langchain')
def chat_agent_langchain(
    debug: bool = typer.Option(
        False,
        '--debug',
        '-d',
        help='Show LangChain reasoning and tool calls',
    ),
) -> None:
    """Start an interactive chat with the LangChain agent.

    Args:
        debug: Whether to enable verbose LangChain logs.
    """
    set_debug_mode(debug)
    assistant = LangChainCompanyAssistant(debug=debug, use_cache=CACHE_ENABLED)

    if assistant.documents:
        console.print(f'[green]✓ Loaded {len(assistant.documents)} documents[/green]')
    else:
        console.print('[yellow]⚠️  No documents found in knowledge_base/[/yellow]')
        console.print('[dim]Create the folder and add your .md files[/dim]')

    print_welcome(debug)

    while True:
        try:
            query = console.input('\n[bold blue]You:[/bold blue] ').strip()

            if not query:
                continue

            query_lower = query.lower()

            if query_lower in ('quit', 'exit'):
                console.print('[green]Goodbye! 👋[/green]')
                break

            if query_lower == 'reset':
                assistant.reset()
                console.print('[yellow]Conversation reset[/yellow]')
                continue

            if query_lower == 'docs':
                if assistant.documents:
                    console.print('\n[bold]Available documents:[/bold]')
                    for name, doc in assistant.documents.items():
                        summary = getattr(doc, 'summary', '')
                        console.print(f'  • {name}: {summary}')
                else:
                    console.print('[yellow]No documents loaded[/yellow]')
                continue

            if query_lower == 'cache':
                if assistant.cache:
                    print_cache_stats(assistant.cache.stats())
                else:
                    console.print('[yellow]Cache not available[/yellow]')
                continue

            if query_lower == 'cache clear':
                if assistant.cache:
                    deleted = assistant.cache.clear()
                    console.print(
                        f'[yellow]Cache cleared ({deleted} entries removed)[/yellow]'
                    )
                else:
                    console.print('[yellow]Cache not available[/yellow]')
                continue

            if debug:
                response = assistant.process_query(query)
            else:
                with console.status('[bold green]Thinking...'):
                    response = assistant.process_query(query)

            console.print(f'\n[bold green]Assistant:[/bold green] {response}')

        except KeyboardInterrupt:
            console.print('\n[green]Goodbye! 👋[/green]')
            break
        except Exception as exc:
            console.print(f'[red]Error:[/red] {exc}')
            if debug:
                console.print(traceback.format_exc())


@app.command()
def cache_clear() -> None:
    """Clear the query cache."""
    assistant = CompanyAssistant(use_cache=True)
    if assistant.cache:
        deleted = assistant.cache.clear()
        console.print(f'[green]Cache cleared ({deleted} entries removed)[/green]')
    else:
        console.print('[yellow]Cache not available[/yellow]')


@app.command()
def db_migrate() -> None:
    """Run pending database migrations."""
    manager = MigrationManager()
    try:
        results = manager.migrate()

        if results['applied']:
            console.print('[green]✓ Applied migrations:[/green]')
            for version in results['applied']:
                console.print(f'  • {version}')

        if results['failed']:
            console.print('[red]✗ Failed migrations:[/red]')
            for version in results['failed']:
                console.print(f'  • {version}')

        if not results['applied'] and not results['failed']:
            console.print('[green]✓ Database is up to date[/green]')
    finally:
        manager.close()


@app.command()
def db_status() -> None:
    """Show database migration status."""
    manager = MigrationManager()
    try:
        status = manager.status()

        table = Table(title='🗄️ Migration Status')
        table.add_column('Status', style='cyan')
        table.add_column('Migrations', style='green')

        table.add_row('Applied', str(status['total_applied']))
        table.add_row('Pending', str(status['total_pending']))

        console.print(table)

        if status['applied']:
            console.print('\n[bold]Applied migrations:[/bold]')
            for version in status['applied']:
                console.print(f'  [green]✓[/green] {version}')

        if status['pending']:
            console.print('\n[bold]Pending migrations:[/bold]')
            for version in status['pending']:
                console.print(f'  [yellow]○[/yellow] {version}')
    finally:
        manager.close()


if __name__ == '__main__':
    app()
