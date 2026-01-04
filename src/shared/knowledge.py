from dataclasses import dataclass

from config import KNOWLEDGE_BASE_DIR


@dataclass
class Document:
    """Container for a knowledge base document."""

    name: str
    filename: str
    content: str
    summary: str | None


DOC_SUMMARIES = {
    'coding_style.md': (
        'ZURU Melon Coding Style Guide (v1.0): '
        'general engineering principles (clarity, consistency, documentation, testing), '
        'Python standards (PEP8, type hints, mypy, exception handling, AI logging), '
        'TypeScript standards (Prettier, typing, React functional components), '
        'testing requirements (pytest, jest, 90% coverage), '
        'security best practices, CI/CD rules, linters, pre-commit hooks, '
        'and mandatory code review process.'
    ),
    'company_policies.md': (
        'ZURU Melon Company Policies: '
        'mission and company values, code of conduct, integrity and confidentiality, '
        'AI ethics and responsible AI use (bias prevention, audits, ethics reporting), '
        'data security and privacy (GDPR, encryption, access control), '
        'intellectual property ownership, remote and flexible work policy, '
        'diversity and inclusion, client communication standards, '
        'use of company technology, social media rules, '
        'and procedures for reporting misconduct or ethical issues.'
    ),
    'company_procedures.md': (
        'ZURU Melon Company Procedures & Guidelines (v1.1): '
        'recruitment and hiring process (job posting, screening, interviews, offers), '
        'onboarding workflow (welcome kit, orientation, 30-60-90 day plan), '
        'working hours, vacation and leave request process, sick leave rules, '
        'AI project lifecycle (client onboarding, discovery, POC, delivery, post-support), '
        'internal and client complaint handling procedures, '
        'data security enforcement, GDPR compliance, '
        'and ethical review process for AI projects.'
    ),
}


def load_documents() -> dict[str, Document]:
    """Load all markdown documents from the knowledge base.

    Returns:
        A mapping of filename to Document metadata and contents.
    """
    documents: dict[str, Document] = {}

    if not KNOWLEDGE_BASE_DIR.exists():
        return documents

    for file_path in KNOWLEDGE_BASE_DIR.glob('*.md'):
        filename = file_path.name
        content = file_path.read_text(encoding='utf-8')

        summary = DOC_SUMMARIES.get(filename)

        documents[filename] = Document(
            name=file_path.stem.replace('_', ' ').title(),
            filename=filename,
            content=content,
            summary=summary,
        )

    return documents


def get_doc_summaries_prompt(documents: dict[str, Document]) -> str:
    """Generate a prompt listing available documents and their summaries.

    Args:
        documents: Mapping of filenames to Document instances.

    Returns:
        A formatted prompt listing documents and summaries.
    """
    lines = ['Available company documents:']
    for filename, doc in documents.items():
        lines.append(f'- {filename}: {doc.summary}')
    return '\n'.join(lines)
