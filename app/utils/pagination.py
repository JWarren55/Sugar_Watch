"""Bound page sizes and preserve independent history and saved-food controls."""

from math import ceil

from fastapi import HTTPException

PAGE_SIZES = (10, 25, 50, 100)


def page_options(request, prefix=""):
    key = prefix + "page"
    size_key = prefix + "per_page"
    try:
        number = int(request.query_params.get(key, "1"))
        size = int(request.query_params.get(size_key, "25"))
    except ValueError as exc:
        raise HTTPException(400, "Choose a valid page number and page size.") from exc
    if number < 1 or size not in PAGE_SIZES:
        raise HTTPException(
            400, "Page must be at least 1; choose 10, 25, 50, or 100 items."
        )
    return key, size_key, number, size


def paginate(query, request, prefix=""):
    key, size_key, number, size = page_options(request, prefix)
    total = query.order_by(None).count()
    pages = max(1, ceil(total / size))
    number = min(number, pages)
    rows = query.offset((number - 1) * size).limit(size).all()

    def url(page):
        return str(request.url.include_query_params(**{key: page, size_key: size}))

    info = {
        "path": request.url.path,
        "page": number,
        "pages": pages,
        "per_page": size,
        "total": total,
        "start": (number - 1) * size + 1 if total else 0,
        "end": min(number * size, total),
        "previous": url(number - 1) if number > 1 else None,
        "next": url(number + 1) if number < pages else None,
        "page_key": key,
        "size_key": size_key,
        "choices": PAGE_SIZES,
        "hidden": [
            (k, v)
            for k, v in request.query_params.multi_items()
            if k not in (key, size_key)
        ],
    }
    return rows, info
