from __future__ import annotations

from collections.abc import Sequence


def normalize_search_terms(search: str | None, *, max_terms: int = 6) -> list[str]:
    raw = " ".join(str(search or "").split()).strip()
    if not raw:
        return []

    terms = [term for term in raw.split(" ") if term]
    if max_terms > 0:
        terms = terms[:max_terms]
    return terms


def build_tokenized_like_clause(
    columns: Sequence[str],
    search: str | None,
    *,
    max_terms: int = 6,
) -> tuple[str, list[str]]:
    terms = normalize_search_terms(search, max_terms=max_terms)
    if not terms:
        return "", []

    groups: list[str] = []
    params: list[str] = []
    column_sql = " OR ".join(f"{column} LIKE %s" for column in columns)

    for term in terms:
        like = f"%{term}%"
        groups.append(f"({column_sql})")
        params.extend([like] * len(columns))

    return "(" + " AND ".join(groups) + ")", params
