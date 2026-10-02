import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models import DBHelpArticle, DBHelpCategory
from app.schemas import (
    HelpArticleResponse,
    HelpArticleSummaryResponse,
    HelpCategoryDetailResponse,
    HelpCategoryResponse,
    HelpSearchResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/help",
    tags=["Help Center"],
)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@router.get(
    "/categories",
    response_model=list[HelpCategoryResponse],
)
async def get_help_categories(
    db: AsyncSession = Depends(get_db),
):
    article_count = (
        select(
            DBHelpArticle.category_id,
            func.count(DBHelpArticle.id).label("article_count"),
        )
        .where(DBHelpArticle.is_published.is_(True))
        .group_by(DBHelpArticle.category_id)
        .subquery()
    )

    result = await db.execute(
        select(
            DBHelpCategory,
            func.coalesce(article_count.c.article_count, 0).label(
                "article_count"
            ),
        )
        .outerjoin(
            article_count,
            article_count.c.category_id == DBHelpCategory.id,
        )
        .where(DBHelpCategory.is_active.is_(True))
        .order_by(DBHelpCategory.sort_order.asc(), DBHelpCategory.id.asc())
    )

    return [
        HelpCategoryResponse(
            id=category.id,
            slug=category.slug,
            title=category.title,
            description=category.description,
            icon=category.icon,
            sort_order=category.sort_order,
            article_count=article_count,
        )
        for category, article_count in result.all()
    ]


@router.get(
    "/categories/{slug}",
    response_model=HelpCategoryDetailResponse,
)
async def get_help_category(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    category = (
        await db.execute(
            select(DBHelpCategory).where(
                DBHelpCategory.slug == slug,
                DBHelpCategory.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Help category not found",
        )

    result = await db.execute(
        select(DBHelpArticle)
        .where(
            DBHelpArticle.category_id == category.id,
            DBHelpArticle.is_published.is_(True),
        )
        .order_by(
            DBHelpArticle.sort_order.asc(),
            DBHelpArticle.id.asc(),
        )
    )

    articles = result.scalars().all()

    return HelpCategoryDetailResponse(
        id=category.id,
        slug=category.slug,
        title=category.title,
        description=category.description,
        icon=category.icon,
        sort_order=category.sort_order,
        article_count=len(articles),
        articles=[
            HelpArticleSummaryResponse(
                id=article.id,
                slug=article.slug,
                title=article.title,
                excerpt=article.excerpt,
                icon=article.icon,
                category_slug=category.slug,
                category_title=category.title,
                is_featured=article.is_featured,
            )
            for article in articles
        ],
    )


# ---------------------------------------------------------------------------
# Featured / Frequently Asked
# ---------------------------------------------------------------------------


@router.get(
    "/featured",
    response_model=list[HelpArticleSummaryResponse],
)
async def get_featured_help_articles(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            DBHelpArticle,
            DBHelpCategory.slug.label("category_slug"),
            DBHelpCategory.title.label("category_title"),
        )
        .join(
            DBHelpCategory,
            DBHelpCategory.id == DBHelpArticle.category_id,
        )
        .where(
            DBHelpArticle.is_published.is_(True),
            DBHelpArticle.is_featured.is_(True),
            DBHelpCategory.is_active.is_(True),
        )
        .order_by(
            DBHelpArticle.sort_order.asc(),
            DBHelpArticle.id.asc(),
        )
        .limit(limit)
    )

    return [
        HelpArticleSummaryResponse(
            id=article.id,
            slug=article.slug,
            title=article.title,
            excerpt=article.excerpt,
            icon=article.icon,
            category_slug=category_slug,
            category_title=category_title,
            is_featured=article.is_featured,
        )
        for article, category_slug, category_title in result.all()
    ]


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------


@router.get(
    "/articles",
    response_model=list[HelpArticleSummaryResponse],
)
async def get_help_articles(
    category: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(
            DBHelpArticle,
            DBHelpCategory.slug.label("category_slug"),
            DBHelpCategory.title.label("category_title"),
        )
        .join(
            DBHelpCategory,
            DBHelpCategory.id == DBHelpArticle.category_id,
        )
        .where(
            DBHelpArticle.is_published.is_(True),
            DBHelpCategory.is_active.is_(True),
        )
    )

    if category:
        query = query.where(DBHelpCategory.slug == category)

    query = (
        query.order_by(
            DBHelpArticle.sort_order.asc(),
            DBHelpArticle.id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)

    return [
        HelpArticleSummaryResponse(
            id=article.id,
            slug=article.slug,
            title=article.title,
            excerpt=article.excerpt,
            icon=article.icon,
            category_slug=category_slug,
            category_title=category_title,
            is_featured=article.is_featured,
        )
        for article, category_slug, category_title in result.all()
    ]


@router.get(
    "/articles/{slug}",
    response_model=HelpArticleResponse,
)
async def get_help_article(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            DBHelpArticle,
            DBHelpCategory.slug.label("category_slug"),
            DBHelpCategory.title.label("category_title"),
        )
        .join(
            DBHelpCategory,
            DBHelpCategory.id == DBHelpArticle.category_id,
        )
        .where(
            DBHelpArticle.slug == slug,
            DBHelpArticle.is_published.is_(True),
            DBHelpCategory.is_active.is_(True),
        )
    )

    row = result.one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Help article not found",
        )

    article, category_slug, category_title = row

    return HelpArticleResponse(
        id=article.id,
        category_id=article.category_id,
        slug=article.slug,
        title=article.title,
        excerpt=article.excerpt,
        content=article.content,
        icon=article.icon,
        tags=article.tags or [],
        search_keywords=article.search_keywords,
        sort_order=article.sort_order,
        is_featured=article.is_featured,
        is_published=article.is_published,
        category_slug=category_slug,
        category_title=category_title,
        created_at=article.created_at,
        updated_at=article.updated_at,
        published_at=article.published_at,
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@router.get(
    "/search",
    response_model=HelpSearchResponse,
)
async def search_help_articles(
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    search = q.strip()

    if len(search) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query must contain at least 2 characters",
        )

    pattern = f"%{search}%"

    conditions = or_(
        DBHelpArticle.title.ilike(pattern),
        DBHelpArticle.excerpt.ilike(pattern),
        DBHelpArticle.content.ilike(pattern),
        DBHelpArticle.search_keywords.ilike(pattern),
        DBHelpCategory.title.ilike(pattern),
    )

    count_result = await db.execute(
        select(func.count(DBHelpArticle.id))
        .join(
            DBHelpCategory,
            DBHelpCategory.id == DBHelpArticle.category_id,
        )
        .where(
            DBHelpArticle.is_published.is_(True),
            DBHelpCategory.is_active.is_(True),
            conditions,
        )
    )

    total = count_result.scalar_one()

    result = await db.execute(
        select(
            DBHelpArticle,
            DBHelpCategory.slug.label("category_slug"),
            DBHelpCategory.title.label("category_title"),
        )
        .join(
            DBHelpCategory,
            DBHelpCategory.id == DBHelpArticle.category_id,
        )
        .where(
            DBHelpArticle.is_published.is_(True),
            DBHelpCategory.is_active.is_(True),
            conditions,
        )
        .order_by(
            DBHelpArticle.is_featured.desc(),
            DBHelpArticle.sort_order.asc(),
            DBHelpArticle.id.asc(),
        )
        .limit(limit)
    )

    articles = [
        HelpArticleSummaryResponse(
            id=article.id,
            slug=article.slug,
            title=article.title,
            excerpt=article.excerpt,
            icon=article.icon,
            category_slug=category_slug,
            category_title=category_title,
            is_featured=article.is_featured,
        )
        for article, category_slug, category_title in result.all()
    ]

    return HelpSearchResponse(
        results=articles,
        query=search,
        total=total,
    )
