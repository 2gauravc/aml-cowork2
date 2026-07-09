#!/usr/bin/env python3
"""
Find and summarize available KYC sandbox test cases.

The main callable for future LLM tool binding is:
    find_test_cases(query=None, jurisdiction=None, country=None, origin=None)

For local testing:
    python tools/case_finder.py
    python tools/case_finder.py --jurisdiction HK
    python tools/case_finder.py --query ubizense
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = PROJECT_ROOT / "data" / "kyc-sandbox-test-cases.json"
MAX_LIMIT = 25
COUNTRY_ALIASES = {
    "britain": {"jurisdiction": "GB"},
    "england": {"jurisdiction": "GB"},
    "great britain": {"jurisdiction": "GB"},
    "scotland": {"jurisdiction": "GB"},
    "uk": {"jurisdiction": "GB"},
    "united kingdom": {"country": "united kingdom"},
    "wales": {"jurisdiction": "GB"},
}


def find_test_cases(
    query: str | None = None,
    jurisdiction: str | None = None,
    country: str | None = None,
    origin: str | None = None,
    view: str | None = None,
    *,
    limit: int = 5,
    include_summary: bool = True,
    cases_path: str | Path = DEFAULT_CASES_PATH,
) -> dict[str, Any]:
    """
    Finds relevant KYC sandbox test cases and returns a compact summary.

    Args:
        query (str | None): Optional company name or keyword to search for.
        jurisdiction (str | None): Optional jurisdiction code, for example "HK".
        country (str | None): Optional country name filter, for example
            "Hong Kong".
        origin (str | None): Optional case source filter, for example "golden",
            "synthetic", or "registry-harvest".
        view (str | None): Optional output shape. Use "jurisdiction_counts" to
            aggregate matching cases by jurisdiction instead of returning entity
            rows. Defaults to "entities".
        limit (int): Maximum number of matching cases to return. Defaults to 5
            and is capped at 25 to avoid dumping the full dataset.
        include_summary (bool): Whether to include dataset counts and top
            jurisdictions/origins. Defaults to True.
        cases_path (str | Path): Path to the sandbox cases JSON file. Defaults
            to data/kyc-sandbox-test-cases.json.

    Returns:
        dict[str, Any]: A compact summary plus selected matching cases. The
            response is intentionally limited so the LLM can reason over the
            dataset without receiving every case at once. On failure, returns
            a dict with an "error" object and context instead of raising.
    """
    try:
        cases = _load_cases(cases_path)
        filters = _normalise_filters(query, jurisdiction, country, origin)
        view = _normalise_view(view)
        matches = _filter_cases(cases, filters)
        ranked = _rank_cases(matches, filters["query"])
        limit = max(1, min(limit, MAX_LIMIT))

        result = {
            "filters": _drop_empty(filters),
            "view": view,
            "total_matching_cases": len(matches),
        }

        if view == "jurisdiction_counts":
            result["jurisdiction_counts"] = _jurisdiction_count_rows(matches)
        else:
            result.update(
                {
                    "returned_cases": [_clean_case(case) for case in ranked[:limit]],
                    "returned_count": min(len(matches), limit),
                    "limit": limit,
                }
            )

        if include_summary:
            result["summary"] = _summary(cases, matches)

        if view != "jurisdiction_counts" and len(matches) > limit:
            result["note"] = (
                f"{len(matches) - limit} additional cases matched. Narrow the "
                "filters or increase limit to inspect more."
            )

        return _drop_empty(result)
    except Exception as exc:
        return _error_response(
            exc,
            query=query,
            jurisdiction=jurisdiction,
            country=country,
            origin=origin,
            view=view,
            cases_path=str(cases_path),
        )


def _load_cases(cases_path: str | Path) -> list[dict[str, Any]]:
    path = Path(cases_path)
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, list):
        raise ValueError(f"Expected a list of cases in {path}")
    return [case for case in data if isinstance(case, dict)]


def _normalise_filters(
    query: str | None,
    jurisdiction: str | None,
    country: str | None,
    origin: str | None,
) -> dict[str, str | None]:
    normalized_country = country.strip().casefold() if country else None
    normalized_jurisdiction = jurisdiction.strip().upper() if jurisdiction else None
    alias = COUNTRY_ALIASES.get(normalized_country or "")
    if alias and not normalized_jurisdiction:
        normalized_jurisdiction = alias.get("jurisdiction")
        normalized_country = alias.get("country")

    return {
        "query": query.strip().casefold() if query else None,
        "jurisdiction": normalized_jurisdiction,
        "country": normalized_country,
        "origin": origin.strip().casefold() if origin else None,
    }


def _normalise_view(view: str | None) -> str:
    normalized = str(view or "entities").strip().casefold()
    if normalized in {"jurisdiction_counts", "jurisdiction_count", "counts_by_jurisdiction"}:
        return "jurisdiction_counts"
    return "entities"


def _filter_cases(
    cases: list[dict[str, Any]],
    filters: dict[str, str | None],
) -> list[dict[str, Any]]:
    matches = []
    for case in cases:
        if filters["jurisdiction"] and case.get("jurisdiction") != filters["jurisdiction"]:
            continue
        if filters["origin"] and str(case.get("origin", "")).casefold() != filters["origin"]:
            continue
        if filters["country"] and filters["country"] not in str(
            case.get("countryName", "")
        ).casefold():
            continue
        if filters["query"] and filters["query"] not in str(case.get("name", "")).casefold():
            continue
        matches.append(case)
    return matches


def _rank_cases(cases: list[dict[str, Any]], query: str | None) -> list[dict[str, Any]]:
    if not query:
        return cases

    def score(case: dict[str, Any]) -> tuple[int, str]:
        name = str(case.get("name", "")).casefold()
        if name == query:
            return (0, name)
        if name.startswith(query):
            return (1, name)
        return (2, name)

    return sorted(cases, key=score)


def _jurisdiction_count_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(case.get("jurisdiction") for case in cases)
    return _counter_items(counts, limit=None)


def _summary(
    all_cases: list[dict[str, Any]],
    matches: list[dict[str, Any]],
) -> dict[str, Any]:
    jurisdiction_counts = Counter(case.get("jurisdiction") for case in all_cases)
    origin_counts = Counter(case.get("origin") for case in all_cases)
    match_jurisdiction_counts = Counter(case.get("jurisdiction") for case in matches)
    hk_count = jurisdiction_counts.get("HK", 0)

    return {
        "summary_text": (
            f"There are {len(all_cases)} sandbox cases across "
            f"{len([key for key in jurisdiction_counts if key])} jurisdictions. "
            f"Hong Kong (HK) has {hk_count} cases. The largest jurisdiction is "
            f"{jurisdiction_counts.most_common(1)[0][0]} with "
            f"{jurisdiction_counts.most_common(1)[0][1]} cases."
        ),
        "total_cases": len(all_cases),
        "total_jurisdictions": len([key for key in jurisdiction_counts if key]),
        "hong_kong_cases": hk_count,
        "top_jurisdictions": _counter_items(jurisdiction_counts, limit=10),
        "origin_counts": _counter_items(origin_counts, limit=10),
        "matching_jurisdictions": _counter_items(match_jurisdiction_counts, limit=10),
    }


def _counter_items(counter: Counter, *, limit: int | None) -> list[dict[str, Any]]:
    items = [
        {"value": value, "count": count}
        for value, count in counter.most_common(limit)
        if value not in (None, "")
    ]
    return sorted(items, key=lambda item: (-item["count"], item["value"]))


def _clean_case(case: dict[str, Any]) -> dict[str, Any]:
    return _drop_empty(
        {
            "name": case.get("name"),
            "jurisdiction": case.get("jurisdiction"),
            "country_name": case.get("countryName"),
            "registration_number": case.get("registrationNumber"),
            "origin": case.get("origin"),
        }
    )


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item = _drop_empty(item)
            if item in (None, "", [], {}):
                continue
            cleaned[key] = item
        return cleaned

    if isinstance(value, list):
        return [_drop_empty(item) for item in value if item not in (None, "", [], {})]

    return value


def _error_response(exc: Exception, **context: Any) -> dict[str, Any]:
    return _drop_empty(
        {
            "error": {
                "type": exc.__class__.__name__,
                "message": str(exc),
            },
            "context": context,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Find KYC sandbox test cases")
    parser.add_argument("--query", help="Company name or keyword to search")
    parser.add_argument("--jurisdiction", help='Jurisdiction code, e.g. "HK"')
    parser.add_argument("--country", help='Country name, e.g. "Hong Kong"')
    parser.add_argument("--origin", help='Case origin, e.g. "golden"')
    parser.add_argument(
        "--view",
        choices=("entities", "jurisdiction_counts"),
        default="entities",
        help="Return entity rows or aggregate counts by jurisdiction",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help=f"Maximum cases to return. Capped at {MAX_LIMIT}",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Return matching cases without dataset summary counts",
    )
    args = parser.parse_args()

    result = find_test_cases(
        query=args.query,
        jurisdiction=args.jurisdiction,
        country=args.country,
        origin=args.origin,
        view=args.view,
        limit=args.limit,
        include_summary=not args.no_summary,
    )
    json.dump(result, fp=sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
