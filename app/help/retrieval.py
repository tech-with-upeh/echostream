from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Float, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.help_models import DBHelpArticle, DBHelpCategory


@dataclass(frozen=True)
class HelpRetrievalResult:
    article_id: int
    slug: str
    title: str
    category_slug: str
    category_title: str
    excerpt: str | None
    content: str
    score: float


def _document():
    return (
        func.setweight(func.to_tsvector("english", func.coalesce(DBHelpArticle.title, "")), "A")
        .op("||")(func.setweight(func.to_tsvector("english", func.coalesce(DBHelpArticle.search_keywords, "")), "A"))
        .op("||")(func.setweight(func.to_tsvector("english", func.coalesce(DBHelpArticle.excerpt, "")), "B"))
        .op("||")(func.setweight(func.to_tsvector("english", func.coalesce(DBHelpArticle.content, "")), "C"))
    )


async def search_help(session: AsyncSession, query: str, *, limit: int = 5) -> list[HelpRetrievalResult]:
    search = query.strip()
    if not search:
        return []

    limit = max(1, min(limit, 10))
    ts_query = func.websearch_to_tsquery("english", search)
    document = _document()
    rank = func.ts_rank_cd(document, ts_query)
    exact_title_bonus = case(
        (func.lower(DBHelpArticle.title) == func.lower(literal(search)), 0.25),
        else_=0.0,
    )

    stmt = (
        select(
            DBHelpArticle.id,
            DBHelpArticle.slug,
            DBHelpArticle.title,
            DBHelpCategory.slug.label("category_slug"),
            DBHelpCategory.title.label("category_title"),
            DBHelpArticle.excerpt,
            DBHelpArticle.content,
            (rank + exact_title_bonus).cast(Float).label("score"),
        )
        .join(DBHelpCategory, DBHelpCategory.id == DBHelpArticle.category_id)
        .where(
            DBHelpArticle.is_published.is_(True),
            DBHelpCategory.is_active.is_(True),
            document.bool_op("@@")(ts_query),
        )
        .order_by((rank + exact_title_bonus).desc(), DBHelpArticle.is_featured.desc(), DBHelpArticle.sort_order.asc(), DBHelpArticle.id.asc())
        .limit(limit)
    )

    rows = (await session.execute(stmt)).all()
    return [
        HelpRetrievalResult(
            article_id=row.id,
            slug=row.slug,
            title=row.title,
            category_slug=row.category_slug,
            category_title=row.category_title,
            excerpt=row.excerpt,
            content=row.content,
            score=float(row.score or 0),
        )
        for row in rows
    ]


def _compact_content(content: str, query: str, max_chars: int = 700) -> str:
    text = " ".join(content.split())
    if len(text) <= max_chars:
        return text

    terms = [term.strip(".,!?;:()[]{}\\\"'").lower() for term in query.split() if len(term.strip(".,!?;:()[]{}\\\"'")) >= 3]
    lowered = text.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if not positions:
        return text[:max_chars].rstrip() + "…"

    start = max(0, min(positions) - max_chars // 3)
    snippet = text[start:start + max_chars].strip()
    if start > 0:
        snippet = "… " + snippet
    if start + max_chars < len(text):
        snippet += " …"
    return snippet


def format_help_context(results: list[HelpRetrievalResult], query: str, *, max_chars: int = 6000) -> str:
    blocks: list[str] = []
    total = 0
    for index, result in enumerate(results, start=1):
        block = (
            f"[Source {index}]\\n"
            f"Title: {result.title}\\n"
            f"Category: {result.category_title}\\n"
            f"Slug: {result.slug}\\n"
            f"Content: {_compact_content(result.content, query)}"
        )
        if total + len(block) > max_chars:
            break
        blocks.append(block)
        total += len(block) + 2
    return "\\n\\n".join(blocks)
