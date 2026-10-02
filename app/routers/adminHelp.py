from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


from app.dependencies import get_current_user, require_admin, get_db
from app.models import DBHelpArticle, DBHelpCategory, DBUser
from app.schemas import (
    HelpArticleCreate,
    HelpArticleResponse,
    HelpArticleUpdate,
    HelpCategoryCreate,
    HelpCategoryDetailResponse,
    HelpCategoryResponse,
    HelpCategoryUpdate,
)
from app.scripts.helpdesk_seed import CATEGORIES, ARTICLES

router = APIRouter(
    prefix="/admin/help",
    tags=["Admin - Help Center"],
)

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@router.get(
    "/categories",
    response_model=list[HelpCategoryResponse],
)
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _: DBUser = Depends(require_admin),
):
    result = await db.execute(
        select(DBHelpCategory)
        .order_by(
            DBHelpCategory.sort_order.asc(),
            DBHelpCategory.id.asc(),
        )
    )

    categories = result.scalars().all()

    responses = []

    for category in categories:
        article_count_result = await db.execute(
            select(DBHelpArticle.id)
            .where(
                DBHelpArticle.category_id == category.id,
                DBHelpArticle.is_published.is_(True),
            )
        )

        article_count = len(article_count_result.scalars().all())

        responses.append(
            HelpCategoryResponse(
                id=category.id,
                slug=category.slug,
                title=category.title,
                description=category.description,
                icon=category.icon,
                sort_order=category.sort_order,
                article_count=article_count,
            )
        )

    return responses


@router.post(
    "/categories",
    response_model=HelpCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    payload: HelpCategoryCreate,
    db: AsyncSession = Depends(get_db),
    _: DBUser = Depends(require_admin),
):
    existing = await db.execute(
        select(DBHelpCategory).where(
            DBHelpCategory.slug == payload.slug
        )
    )

    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A category with this slug already exists",
        )

    now = datetime.now(timezone.utc)

    category = DBHelpCategory(
        slug=payload.slug,
        title=payload.title,
        description=payload.description,
        icon=payload.icon,
        sort_order=payload.sort_order,
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    db.add(category)
    await db.commit()
    await db.refresh(category)

    return HelpCategoryResponse(
        id=category.id,
        slug=category.slug,
        title=category.title,
        description=category.description,
        icon=category.icon,
        sort_order=category.sort_order,
        article_count=0,
    )


@router.get(
    "/categories/{category_id}",
    response_model=HelpCategoryDetailResponse,
)
async def get_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _: DBUser = Depends(require_admin),
):
    result = await db.execute(
        select(DBHelpCategory).where(
            DBHelpCategory.id == category_id
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Help category not found",
        )

    article_result = await db.execute(
        select(DBHelpArticle)
        .where(DBHelpArticle.category_id == category.id)
        .order_by(
            DBHelpArticle.sort_order.asc(),
            DBHelpArticle.id.asc(),
        )
    )

    articles = article_result.scalars().all()

    article_responses = [
        {
            "id": article.id,
            "slug": article.slug,
            "title": article.title,
            "excerpt": article.excerpt,
            "icon": article.icon,
            "category_slug": category.slug,
            "category_title": category.title,
            "is_featured": article.is_featured,
        }
        for article in articles
    ]

    return HelpCategoryDetailResponse(
        id=category.id,
        slug=category.slug,
        title=category.title,
        description=category.description,
        icon=category.icon,
        sort_order=category.sort_order,
        article_count=len(articles),
        articles=article_responses,
    )


@router.patch(
    "/categories/{category_id}",
    response_model=HelpCategoryResponse,
)
async def update_category(
    category_id: int,
    payload: HelpCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _: DBUser = Depends(require_admin),
):
    result = await db.execute(
        select(DBHelpCategory).where(
            DBHelpCategory.id == category_id
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Help category not found",
        )

    if payload.slug is not None and payload.slug != category.slug:
        existing = await db.execute(
            select(DBHelpCategory).where(
                DBHelpCategory.slug == payload.slug,
                DBHelpCategory.id != category.id,
            )
        )

        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A category with this slug already exists",
            )

        category.slug = payload.slug

    if payload.title is not None:
        category.title = payload.title

    if payload.description is not None:
        category.description = payload.description

    if payload.icon is not None:
        category.icon = payload.icon

    if payload.sort_order is not None:
        category.sort_order = payload.sort_order

    if payload.is_active is not None:
        category.is_active = payload.is_active

    category.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(category)

    article_count_result = await db.execute(
        select(DBHelpArticle.id).where(
            DBHelpArticle.category_id == category.id,
            DBHelpArticle.is_published.is_(True),
        )
    )

    article_count = len(article_count_result.scalars().all())

    return HelpCategoryResponse(
        id=category.id,
        slug=category.slug,
        title=category.title,
        description=category.description,
        icon=category.icon,
        sort_order=category.sort_order,
        article_count=article_count,
    )


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _: DBUser = Depends(require_admin),
):
    result = await db.execute(
        select(DBHelpCategory).where(
            DBHelpCategory.id == category_id
        )
    )

    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Help category not found",
        )

    await db.delete(category)
    await db.commit()


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------

@router.get(
    "/articles",
    response_model=list[HelpArticleResponse],
)
async def list_articles(
    category_id: int | None = Query(default=None),
    published_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _: DBUser = Depends(require_admin),
):
    query = (
        select(DBHelpArticle, DBHelpCategory)
        .join(
            DBHelpCategory,
            DBHelpArticle.category_id == DBHelpCategory.id,
        )
        .order_by(
            DBHelpArticle.sort_order.asc(),
            DBHelpArticle.id.asc(),
        )
    )

    if category_id is not None:
        query = query.where(
            DBHelpArticle.category_id == category_id
        )

    if published_only:
        query = query.where(
            DBHelpArticle.is_published.is_(True)
        )

    result = await db.execute(query)

    rows = result.all()

    return [
        HelpArticleResponse(
            id=article.id,
            category_id=article.category_id,
            category_slug=category.slug,
            category_title=category.title,
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
            created_at=article.created_at,
            updated_at=article.updated_at,
            published_at=article.published_at,
        )
        for article, category in rows
    ]


@router.post(
    "/articles",
    response_model=HelpArticleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_article(
    payload: HelpArticleCreate,
    db: AsyncSession = Depends(get_db),
    _: DBUser = Depends(require_admin),
):
    category_result = await db.execute(
        select(DBHelpCategory).where(
            DBHelpCategory.id == payload.category_id
        )
    )

    category = category_result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Help category not found",
        )

    existing = await db.execute(
        select(DBHelpArticle).where(
            DBHelpArticle.slug == payload.slug
        )
    )

    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An article with this slug already exists",
        )

    now = datetime.now(timezone.utc)

    published_at = now if payload.is_published else None

    article = DBHelpArticle(
        category_id=payload.category_id,
        slug=payload.slug,
        title=payload.title,
        excerpt=payload.excerpt,
        content=payload.content,
        icon=payload.icon,
        tags=payload.tags,
        search_keywords=payload.search_keywords,
        sort_order=payload.sort_order,
        is_featured=payload.is_featured,
        is_published=payload.is_published,
        created_at=now,
        updated_at=now,
        published_at=published_at,
    )

    db.add(article)
    await db.commit()
    await db.refresh(article)

    return HelpArticleResponse(
        id=article.id,
        category_id=article.category_id,
        category_slug=category.slug,
        category_title=category.title,
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
        created_at=article.created_at,
        updated_at=article.updated_at,
        published_at=article.published_at,
    )


@router.get(
    "/articles/{article_id}",
    response_model=HelpArticleResponse,
)
async def get_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    _: DBUser = Depends(require_admin),
):
    result = await db.execute(
        select(DBHelpArticle, DBHelpCategory)
        .join(
            DBHelpCategory,
            DBHelpArticle.category_id == DBHelpCategory.id,
        )
        .where(DBHelpArticle.id == article_id)
    )

    row = result.first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Help article not found",
        )

    article, category = row

    return HelpArticleResponse(
        id=article.id,
        category_id=article.category_id,
        category_slug=category.slug,
        category_title=category.title,
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
        created_at=article.created_at,
        updated_at=article.updated_at,
        published_at=article.published_at,
    )


@router.patch(
    "/articles/{article_id}",
    response_model=HelpArticleResponse,
)
async def update_article(
    article_id: int,
    payload: HelpArticleUpdate,
    db: AsyncSession = Depends(get_db),
    _: DBUser = Depends(require_admin),
):
    result = await db.execute(
        select(DBHelpArticle).where(
            DBHelpArticle.id == article_id
        )
    )

    article = result.scalar_one_or_none()

    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Help article not found",
        )

    if payload.category_id is not None:
        category_result = await db.execute(
            select(DBHelpCategory).where(
                DBHelpCategory.id == payload.category_id
            )
        )

        if category_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Help category not found",
            )

        article.category_id = payload.category_id

    if payload.slug is not None and payload.slug != article.slug:
        existing = await db.execute(
            select(DBHelpArticle).where(
                DBHelpArticle.slug == payload.slug,
                DBHelpArticle.id != article.id,
            )
        )

        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An article with this slug already exists",
            )

        article.slug = payload.slug

    if payload.title is not None:
        article.title = payload.title

    if payload.excerpt is not None:
        article.excerpt = payload.excerpt

    if payload.content is not None:
        article.content = payload.content

    if payload.icon is not None:
        article.icon = payload.icon

    if payload.tags is not None:
        article.tags = payload.tags

    if payload.search_keywords is not None:
        article.search_keywords = payload.search_keywords

    if payload.sort_order is not None:
        article.sort_order = payload.sort_order

    if payload.is_featured is not None:
        article.is_featured = payload.is_featured

    if payload.is_published is not None:
        was_published = article.is_published
        article.is_published = payload.is_published

        if payload.is_published and not was_published:
            article.published_at = datetime.now(timezone.utc)

        elif not payload.is_published:
            article.published_at = None

    article.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(article)

    category_result = await db.execute(
        select(DBHelpCategory).where(
            DBHelpCategory.id == article.category_id
        )
    )

    category = category_result.scalar_one()

    return HelpArticleResponse(
        id=article.id,
        category_id=article.category_id,
        category_slug=category.slug,
        category_title=category.title,
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
        created_at=article.created_at,
        updated_at=article.updated_at,
        published_at=article.published_at,
    )


@router.delete(
    "/articles/{article_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    _: DBUser = Depends(require_admin),
):
    result = await db.execute(
        select(DBHelpArticle).where(
            DBHelpArticle.id == article_id
        )
    )

    article = result.scalar_one_or_none()

    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Help article not found",
        )

    await db.delete(article)
    await db.commit()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/seed")
async def seed_help_center(
    _admin: DBUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Seed the Help Center categories and articles.

    Safe to call repeatedly:
    - Existing categories are skipped by slug.
    - Existing articles are skipped by slug.
    - Existing content is never overwritten.
    """

    categories_created = 0
    categories_existing = 0
    articles_created = 0
    articles_existing = 0

    # ---------------------------------------------------------
    # Categories
    # ---------------------------------------------------------

    category_map: dict[str, DBHelpCategory] = {}

    for item in CATEGORIES:
        slug = item["slug"]

        result = await db.execute(
            select(DBHelpCategory).where(
                DBHelpCategory.slug == slug
            )
        )

        category = result.scalar_one_or_none()

        if category:
            categories_existing += 1
        else:
            category = DBHelpCategory(
                slug=slug,
                title=item["title"],
                description=item["description"],
                icon=item["icon"],
                sort_order=item.get("sort_order", 0),
                is_active=item.get("is_active", True),
                created_at=now_utc(),
                updated_at=now_utc(),
            )

            db.add(category)
            categories_created += 1

        category_map[slug] = category

    # Flush so newly-created categories receive their IDs.
    await db.flush()

    # ---------------------------------------------------------
    # Articles
    # ---------------------------------------------------------

    for item in ARTICLES:
        slug = item["slug"]

        result = await db.execute(
            select(DBHelpArticle).where(
                DBHelpArticle.slug == slug
            )
        )

        article = result.scalar_one_or_none()

        if article:
            articles_existing += 1
            continue

        category_slug = item["category"]
        category = category_map.get(category_slug)

        if category is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Help article '{slug}' references unknown "
                    f"category '{category_slug}'."
                ),
            )

        published = item.get("is_published", False)

        db.add(
            DBHelpArticle(
                category_id=category.id,
                slug=slug,
                title=item["title"],
                excerpt=item.get("excerpt"),
                content=item["content"],
                icon=item.get("icon"),
                tags=item.get("tags", []),
                search_keywords=item.get("search_keywords"),
                is_featured=item.get("is_featured", False),
                is_published=published,
                sort_order=item.get("sort_order", 0),
                created_at=now_utc(),
                updated_at=now_utc(),
                published_at=now_utc() if published else None,
            )
        )

        articles_created += 1

    await db.commit()

    return {
        "message": "Help Center seed completed successfully.",
        "categories_created": categories_created,
        "categories_existing": categories_existing,
        "articles_created": articles_created,
        "articles_existing": articles_existing,
    }
