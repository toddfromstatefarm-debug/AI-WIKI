#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import random
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import Request, urlopen`r`nfrom duckduckgo_search import DDGS


PREFERRED_DOMAIN_TIERS = {
    "g2.com": 2,
    "trustpilot.com": 2,
    "trustradius.com": 2,
    "capterra.com": 2,
    "demandsage.com": 2,
    "zapier.com": 2,
    "pcmag.com": 2,
    "techradar.com": 2,
    "reddit.com": 3,
    "youtube.com": 3,
}

LOW_TRUST_DOMAINS = {
    "medium.com",
    "blogspot.com",
    "wordpress.com",
    "wixsite.com",
    "quora.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "pinterest.com",
    "x.com",
    "twitter.com",
}

BLOCKED_INTERNAL_DOMAINS = {
    "duckduckgo.com",
    "startpage.com",
    "google.com",
    "bing.com",
    "search.yahoo.com",
}

BLOCKED_FILE_EXTENSIONS = {
    ".js", ".css", ".json", ".xml", ".png", ".jpg", ".jpeg", ".gif",
    ".svg", ".ico", ".webp", ".woff", ".woff2", ".ttf", ".map", ".txt"
}

IRRELEVANT_OFFICIAL_KEYWORDS = {
    "login", "signin", "sign in", "register", "careers", "jobs", "privacy",
    "terms", "legal", "security", "status", "docs", "documentation",
    "developers", "api", "support", "help", "changelog"
}

PRICING_KEYWORDS = {
    "pricing", "plans", "plan", "billing", "subscription", "subscriptions", "cost", "costs"
}
REVIEW_KEYWORDS = {
    "review", "reviews", "rating", "ratings", "hands-on"
}
WORKFLOW_KEYWORDS = {
    "guide", "workflow", "tutorial", "how to", "how-to", "use case", "use-case",
    "walkthrough", "getting started", "review"
}
COMPARISON_KEYWORDS = {
    "alternative", "alternatives", "vs", "versus", "compare", "comparison", "competitor", "competitors"
}
DISCUSSION_KEYWORDS = {
    "thread", "discussion", "comments", "forum", "community"
}
PRODUCT_KEYWORDS = {
    "product", "ai", "features", "overview"
}

INTENT_CAPS = {
    "official": 1,
    "pricing": 2,
    "reviews": 4,
    "workflow": 3,
    "alternatives": 3,
    "discussions": 2,
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect reusable research sources for a tool.")
    parser.add_argument("--tool-name", required=True, help='Public tool name, e.g. "Notion AI"')
    parser.add_argument("--slug", required=True, help='URL/file slug, e.g. "notion"')
    parser.add_argument("--official-url", default="", help="Optional official product URL hint")
    parser.add_argument("--output", default="", help="Optional output path")
    parser.add_argument("--max-results-per-query", type=int, default=5, help="Per-query result cap")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output file")
    return parser


def warn(message: str, warnings_list: list[str]) -> None:
    warnings_list.append(message)
    print(f"WARNING: {message}", file=sys.stderr)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_slug(slug: str) -> bool:
    return re.fullmatch(r"[a-z0-9-]+", slug) is not None


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_string(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return normalize_whitespace(value)


def extract_registered_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        host = host.split("@")[-1].split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        if host.startswith("m."):
            host = host[2:]

        parts = host.split(".")
        if len(parts) < 2:
            return host

        if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "org", "net", "gov", "ac"}:
            return ".".join(parts[-3:])
        return ".".join(parts[-2:])
    except Exception:
        return ""


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc
    path = parsed.path or "/"
    query = ""

    normalized_domain = extract_registered_domain(url)
    if normalized_domain == "youtube.com":
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            query = f"v={qs['v'][0]}"

    built = f"{scheme}://{netloc}{path}"
    if query:
        built += f"?{query}"
    return built


def decode_duckduckgo_redirect(url: str) -> str:
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg", [""])[0]
        if uddg:
            return uddg
    if url.startswith("//duckduckgo.com/l/?"):
        parsed = urlparse("https:" + url)
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg", [""])[0]
        if uddg:
            return uddg
    return url


def is_blocked_extension(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in BLOCKED_FILE_EXTENSIONS)


def contains_keyword(text: str, keywords: set[str]) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in keywords)


def combined_title_path_text(title: str, url: str) -> str:
    parsed = urlparse(url)
    text = f"{title} {parsed.path.replace('-', ' ').replace('_', ' ')}"
    return normalize_whitespace(text).lower()


def is_junk_result(url: str, title: str) -> tuple[bool, str]:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return True, "Rejected because the URL scheme is not http/https."

    if not parsed.netloc:
        return True, "Rejected because the URL has no netloc."

    normalized_domain = extract_registered_domain(url)
    if not normalized_domain:
        return True, "Rejected because the URL has no usable domain."

    if normalized_domain in BLOCKED_INTERNAL_DOMAINS:
        return True, "Rejected because the result is a search-engine internal page."

    path_lower = (parsed.path or "").lower()
    if path_lower in {"/y.js", "/i.js"} or "/y.js" in path_lower or "/i.js" in path_lower:
        return True, "Rejected because the result is a JS endpoint."

    if any(token in path_lower for token in ["/l/", "/js/", "/img/", "/ac/"]):
        return True, "Rejected because the result looks like an internal or asset path."

    if is_blocked_extension(path_lower):
        return True, "Rejected because the result is a non-content asset."

    title_clean = clean_string(title).lower()
    if normalized_domain in BLOCKED_INTERNAL_DOMAINS or "duckduckgo" in title_clean:
        return True, "Rejected because the result appears to be search-engine infrastructure."

    return False, ""


def is_irrelevant_official_result(url: str, title: str, official_domain: str) -> bool:
    normalized_domain = extract_registered_domain(url)
    if normalized_domain != official_domain or not official_domain:
        return False

    text = combined_title_path_text(title, url)
    if contains_keyword(text, IRRELEVANT_OFFICIAL_KEYWORDS) and not contains_keyword(text, PRICING_KEYWORDS):
        return True

    return False


def build_queries(tool_name: str, official_url: str, max_results: int) -> list[dict[str, Any]]:
    official_domain = extract_registered_domain(official_url) if official_url else ""
    queries: list[dict[str, Any]] = []

    if official_domain:
        queries.extend([
            {"intent": "official", "query": f'site:{official_domain} "{tool_name}"', "preferred_domain": official_domain, "max_results": max_results},
            {"intent": "official", "query": f'site:{official_domain} "{tool_name}" AI', "preferred_domain": official_domain, "max_results": max_results},
            {"intent": "official", "query": f'site:{official_domain} "{tool_name}" product', "preferred_domain": official_domain, "max_results": max_results},
            {"intent": "pricing", "query": f'site:{official_domain} "{tool_name}" pricing', "preferred_domain": official_domain, "max_results": max_results},
            {"intent": "pricing", "query": f'site:{official_domain} "{tool_name}" plans', "preferred_domain": official_domain, "max_results": max_results},
            {"intent": "pricing", "query": f'site:{official_domain} "{tool_name}" cost', "preferred_domain": official_domain, "max_results": max_results},
            {"intent": "pricing", "query": f'site:{official_domain} "{tool_name}" billing', "preferred_domain": official_domain, "max_results": max_results},
        ])
    else:
        queries.extend([
            {"intent": "official", "query": f'"{tool_name}" official site', "preferred_domain": "", "max_results": max_results},
            {"intent": "official", "query": f'"{tool_name}" AI official site', "preferred_domain": "", "max_results": max_results},
            {"intent": "pricing", "query": f'"{tool_name}" pricing', "preferred_domain": "", "max_results": max_results},
            {"intent": "pricing", "query": f'"{tool_name}" plans', "preferred_domain": "", "max_results": max_results},
        ])

    review_domains = ["g2.com", "trustpilot.com", "trustradius.com", "capterra.com", "demandsage.com", "zapier.com", "pcmag.com", "techradar.com"]
    workflow_domains = ["zapier.com", "pcmag.com", "techradar.com", "reddit.com", "youtube.com"]
    alternatives_domains = ["zapier.com", "pcmag.com", "techradar.com", "reddit.com", "youtube.com"]
    discussion_domains = ["reddit.com", "youtube.com"]

    for domain in review_domains:
        review_query = f'site:{domain} "{tool_name}"'
        if domain in {"demandsage.com", "zapier.com", "pcmag.com", "techradar.com"}:
            review_query += " review"
        queries.append({"intent": "reviews", "query": review_query, "preferred_domain": domain, "max_results": max_results})

    queries.append({"intent": "reviews", "query": f'"{tool_name}" review', "preferred_domain": "", "max_results": max_results})

    for domain in workflow_domains:
        if domain == "reddit.com":
            q = f'site:{domain} "{tool_name}" workflow'
        elif domain == "youtube.com":
            q = f'site:{domain} "{tool_name}" review'
        else:
            q = f'site:{domain} "{tool_name}" review'
        queries.append({"intent": "workflow", "query": q, "preferred_domain": domain, "max_results": max_results})

    queries.extend([
        {"intent": "workflow", "query": f'"{tool_name}" how to use', "preferred_domain": "", "max_results": max_results},
        {"intent": "workflow", "query": f'"{tool_name}" workflow', "preferred_domain": "", "max_results": max_results},
    ])

    for domain in alternatives_domains:
        q = f'site:{domain} "{tool_name}" alternatives'
        queries.append({"intent": "alternatives", "query": q, "preferred_domain": domain, "max_results": max_results})

    queries.extend([
        {"intent": "alternatives", "query": f'"{tool_name}" alternatives', "preferred_domain": "", "max_results": max_results},
        {"intent": "alternatives", "query": f'"{tool_name}" vs', "preferred_domain": "", "max_results": max_results},
    ])

    for domain in discussion_domains:
        if domain == "reddit.com":
            q = f'site:{domain} "{tool_name}"'
        else:
            q = f'site:{domain} "{tool_name}" review'
        queries.append({"intent": "discussions", "query": q, "preferred_domain": domain, "max_results": max_results})

    queries.extend([
        {"intent": "discussions", "query": f'"{tool_name}" reddit', "preferred_domain": "", "max_results": max_results},
        {"intent": "discussions", "query": f'"{tool_name}" youtube review', "preferred_domain": "", "max_results": max_results},
    ])

    return queries


def fetch_search_results(query: str, max_results: int) -> list[dict[str, str]]:
    """Uses DDGS JSON/text backend — bypasses CAPTCHA completely."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query.strip(), max_results=max_results))
        return [
            {"url": r.get("href", ""), "title": r.get("title", "")}
            for r in results
            if r.get("href")
        ]
    except Exception as exc:
        print(f"Search backend error for '{query}': {exc}")
        return []


def classify_source_roles(intent: str, url: str, title: str, normalized_domain: str, official_domain: str) -> list[str]:
    roles: list[str] = []
    text = combined_title_path_text(title, url)

    if normalized_domain == official_domain and official_domain:
        roles.append("official")

    if normalized_domain == official_domain and (
        urlparse(url).path in {"", "/"} or contains_keyword(text, PRODUCT_KEYWORDS)
    ):
        roles.append("product")

    if contains_keyword(text, PRICING_KEYWORDS):
        roles.append("pricing")

    if normalized_domain in {"g2.com", "trustpilot.com", "trustradius.com", "capterra.com"}:
        roles.append("review-platform")

    if normalized_domain in {"demandsage.com", "zapier.com", "pcmag.com", "techradar.com"} and contains_keyword(text, REVIEW_KEYWORDS):
        roles.append("editorial-review")

    if contains_keyword(text, WORKFLOW_KEYWORDS):
        roles.append("workflow")

    if contains_keyword(text, COMPARISON_KEYWORDS):
        roles.append("comparison")

    if normalized_domain == "reddit.com" or contains_keyword(text, DISCUSSION_KEYWORDS):
        roles.append("discussion")

    if normalized_domain == "youtube.com":
        roles.append("video-review")

    deduped: list[str] = []
    seen = set()
    for role in roles:
        if role not in seen:
            seen.add(role)
            deduped.append(role)
    return deduped


def is_preferred_domain(normalized_domain: str, official_domain: str) -> bool:
    if official_domain and normalized_domain == official_domain:
        return True
    return normalized_domain in PREFERRED_DOMAIN_TIERS


def trust_tier_for_domain(normalized_domain: str, official_domain: str) -> int:
    if official_domain and normalized_domain == official_domain:
        return 1
    if normalized_domain in PREFERRED_DOMAIN_TIERS:
        return PREFERRED_DOMAIN_TIERS[normalized_domain]
    if normalized_domain in LOW_TRUST_DOMAINS:
        return 5
    return 4


def is_valid_for_intent(record: dict[str, Any], intent: str, official_domain: str) -> bool:
    roles = set(record["source_role"])
    normalized_domain = record["normalized_domain"]

    if intent == "official":
        return normalized_domain == official_domain and "official" in roles and "product" in roles

    if intent == "pricing":
        return "pricing" in roles

    if intent == "reviews":
        return "review-platform" in roles or "editorial-review" in roles

    if intent == "workflow":
        return "workflow" in roles or (
            "editorial-review" in roles and normalized_domain in {"zapier.com", "pcmag.com", "techradar.com", "demandsage.com"}
        )

    if intent == "alternatives":
        return "comparison" in roles

    if intent == "discussions":
        return "discussion" in roles or "video-review" in roles

    return False


def make_source_record(
    *,
    url: str,
    title: str,
    intent: str,
    query: str,
    rank: int,
    official_domain: str,
    status: str,
    selection_reason: str,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower()
    normalized_domain = extract_registered_domain(url)
    trust_tier = trust_tier_for_domain(normalized_domain, official_domain)
    preferred = is_preferred_domain(normalized_domain, official_domain)
    source_role = classify_source_roles(intent, url, title, normalized_domain, official_domain)

    return {
        "url": url,
        "title": clean_string(title) or url,
        "domain": domain,
        "normalized_domain": normalized_domain,
        "source_kind": "webpage",
        "trust_tier": trust_tier,
        "source_role": source_role,
        "intents": [intent],
        "found_via_queries": [query],
        "discovered_rank": rank,
        "preferred": preferred,
        "status": status,
        "selection_reason": selection_reason,
        "notes": notes or [],
    }


def merge_source_record(existing: dict[str, Any], new_record: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)

    for intent in new_record.get("intents", []):
        if intent not in merged["intents"]:
            merged["intents"].append(intent)

    for query in new_record.get("found_via_queries", []):
        if query not in merged["found_via_queries"]:
            merged["found_via_queries"].append(query)

    merged["discovered_rank"] = min(merged["discovered_rank"], new_record["discovered_rank"])

    if new_record["trust_tier"] < merged["trust_tier"]:
        merged["trust_tier"] = new_record["trust_tier"]

    for role in new_record.get("source_role", []):
        if role not in merged["source_role"]:
            merged["source_role"].append(role)

    merged["preferred"] = merged["preferred"] or new_record["preferred"]
    return merged


def select_sources(
    raw_sources: list[dict[str, Any]],
    official_domain: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_map: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []

    sorted_sources = sorted(
        raw_sources,
        key=lambda r: (
            r["trust_tier"],
            0 if r["preferred"] else 1,
            r["discovered_rank"],
            r["normalized_domain"],
            r["url"],
        ),
    )

    for intent, cap in INTENT_CAPS.items():
        count = 0
        for record in sorted_sources:
            if count >= cap:
                break

            if not is_valid_for_intent(record, intent, official_domain):
                continue

            url = record["url"]
            if url not in selected_map:
                chosen = deepcopy(record)
                chosen["status"] = "selected"
                chosen["selection_reason"] = f"Selected as a high-trust source for {intent} intent."
                selected_map[url] = chosen
            else:
                if intent not in selected_map[url]["intents"]:
                    selected_map[url]["intents"].append(intent)

            count += 1

    selected_urls = set(selected_map.keys())

    for record in sorted_sources:
        if record["url"] in selected_urls:
            continue

        rejected_record = deepcopy(record)
        rejected_record["status"] = "rejected"

        if record["trust_tier"] == 5:
            rejected_record["selection_reason"] = "Rejected because the domain is low-trust or noisy."
        elif not any(is_valid_for_intent(record, intent, official_domain) for intent in INTENT_CAPS):
            rejected_record["selection_reason"] = "Rejected because title/path heuristics did not validate it for any intent."
        else:
            rejected_record["selection_reason"] = "Rejected because stronger sources already filled the relevant intent quota."

        rejected.append(rejected_record)

    selected = sorted(
        list(selected_map.values()),
        key=lambda r: (r["trust_tier"], 0 if r["preferred"] else 1, r["discovered_rank"], r["url"]),
    )

    rejected = sorted(
        rejected,
        key=lambda r: (r["trust_tier"], 0 if r["preferred"] else 1, r["discovered_rank"], r["url"]),
    )

    return selected, rejected


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    tool_name = clean_string(args.tool_name)
    slug = clean_string(args.slug)
    official_url = clean_string(args.official_url)

    if not tool_name:
        fail("missing required argument: --tool-name")
    if not slug:
        fail("missing required argument: --slug")
    if not validate_slug(slug):
        fail("slug must contain only lowercase letters, numbers, and hyphens.")

    output_path = Path(args.output) if args.output else Path("automation") / "research" / f"{slug}.sources.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and not args.force:
        fail(f"output file already exists: {output_path} (use --force to overwrite)")

    official_domain = extract_registered_domain(official_url) if official_url else ""
    warnings_list: list[str] = []
    queries = build_queries(tool_name, official_url, args.max_results_per_query)

    raw_map: dict[str, dict[str, Any]] = {}
    pre_rejected: list[dict[str, Any]] = []

    if official_url:
        seeded = make_source_record(
            url=canonicalize_url(official_url),
            title=f"{tool_name} (official)",
            intent="official",
            query="official_url_hint",
            rank=0,
            official_domain=official_domain,
            status="candidate",
            selection_reason="Collected from provided official URL hint.",
            notes=["Seeded from official_url hint."],
        )
        raw_map[seeded["url"]] = seeded

    for query_record in queries:
        query = query_record["query"]
        intent = query_record["intent"]

        try:
            results = fetch_search_results(query, query_record["max_results"])
            print(f"DEBUG: {intent} query -> {len(results)} real results parsed (max {query_record['max_results']})")
            time.sleep(random.uniform(1.3, 2.8))
            time.sleep(random.uniform(1.0, 2.0))
        except Exception as exc:
            warn(f"query failed for intent '{intent}': {query} ({exc})", warnings_list)
            continue

        for rank, result in enumerate(results, start=1):
            url = result["url"]
            title = result["title"]

            is_junk, junk_reason = is_junk_result(url, title)
            if is_junk:
                rejected_record = make_source_record(
                    url=url,
                    title=title,
                    intent=intent,
                    query=query,
                    rank=rank,
                    official_domain=official_domain,
                    status="rejected",
                    selection_reason=junk_reason,
                    notes=[],
                )
                pre_rejected.append(rejected_record)
                continue

            if official_domain and is_irrelevant_official_result(url, title, official_domain):
                rejected_record = make_source_record(
                    url=url,
                    title=title,
                    intent=intent,
                    query=query,
                    rank=rank,
                    official_domain=official_domain,
                    status="rejected",
                    selection_reason="Rejected because this official-domain page appears irrelevant to downstream research use.",
                    notes=[],
                )
                pre_rejected.append(rejected_record)
                continue

            candidate = make_source_record(
                url=url,
                title=title,
                intent=intent,
                query=query,
                rank=rank,
                official_domain=official_domain,
                status="candidate",
                selection_reason=f"Collected from query for {intent} intent.",
                notes=[],
            )

            existing = raw_map.get(candidate["url"])
            if existing:
                raw_map[candidate["url"]] = merge_source_record(existing, candidate)
            else:
                raw_map[candidate["url"]] = candidate

    raw_sources = sorted(
        list(raw_map.values()),
        key=lambda r: (r["trust_tier"], 0 if r["preferred"] else 1, r["discovered_rank"], r["url"]),
    )

    selected_sources, rejected_sources = select_sources(raw_sources, official_domain)
    rejected_sources = sorted(
        pre_rejected + rejected_sources,
        key=lambda r: (r["trust_tier"], 0 if r["preferred"] else 1, r["discovered_rank"], r["url"]),
    )

    selected_by_intent = {intent: 0 for intent in INTENT_CAPS}
    for record in selected_sources:
        for intent in INTENT_CAPS:
            if is_valid_for_intent(record, intent, official_domain):
                selected_by_intent[intent] += 1

    for intent in ["official", "pricing", "reviews", "workflow", "alternatives", "discussions"]:
        if selected_by_intent.get(intent, 0) == 0:
            warn(f"No selected source found for {intent} intent.", warnings_list)

    bundle = {
        "tool_name": tool_name,
        "slug": slug,
        "official_url_hint": official_url,
        "collected_at": date.today().isoformat(),
        "collector_version": "v1",
        "queries": queries,
        "raw_sources": raw_sources,
        "selected_sources": selected_sources,
        "rejected_sources": rejected_sources,
        "warnings": warnings_list,
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote research bundle: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


















