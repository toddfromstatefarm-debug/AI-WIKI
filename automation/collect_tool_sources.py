#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import Request, urlopen


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
    parser.add_argument("--max-results-per-query", type=int, default=3, help="Per-query result cap")
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
    path = parsed.path or ""
    return f"{scheme}://{netloc}{path}"


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


def is_preferred_domain(normalized_domain: str, official_domain: str) -> bool:
    if normalized_domain == official_domain and normalized_domain != "":
        return True
    return normalized_domain in PREFERRED_DOMAIN_TIERS


def trust_tier_for_domain(normalized_domain: str, official_domain: str) -> int:
    if normalized_domain == official_domain and normalized_domain != "":
        return 1
    if normalized_domain in PREFERRED_DOMAIN_TIERS:
        return PREFERRED_DOMAIN_TIERS[normalized_domain]
    if normalized_domain in LOW_TRUST_DOMAINS:
        return 5
    return 4


def classify_source_roles(intent: str, normalized_domain: str, official_domain: str) -> list[str]:
    roles: list[str] = []

    if normalized_domain == official_domain and normalized_domain != "":
        roles.append("official")

    if intent == "official":
        roles.append("product")
    elif intent == "pricing":
        roles.append("pricing")
    elif intent == "reviews":
        roles.append("review-platform" if normalized_domain in {
            "g2.com", "trustpilot.com", "trustradius.com", "capterra.com"
        } else "editorial-review")
    elif intent == "workflow":
        roles.append("workflow")
    elif intent == "alternatives":
        roles.append("comparison")
    elif intent == "discussions":
        roles.append("discussion")

    if normalized_domain == "reddit.com":
        roles.append("discussion")
    if normalized_domain == "youtube.com":
        roles.append("video-review")
    if normalized_domain in {"zapier.com", "pcmag.com", "techradar.com", "demandsage.com"}:
        roles.append("editorial-review")
    if normalized_domain in {"g2.com", "trustpilot.com", "trustradius.com", "capterra.com"}:
        roles.append("review-platform")

    deduped: list[str] = []
    seen = set()
    for role in roles:
        if role not in seen:
            seen.add(role)
            deduped.append(role)
    return deduped


def build_queries(tool_name: str, official_url: str, max_results: int) -> list[dict[str, Any]]:
    official_domain = extract_registered_domain(official_url) if official_url else ""
    queries: list[dict[str, Any]] = []

    if official_domain:
        queries.append({
            "intent": "official",
            "query": f'site:{official_domain} "{tool_name}"',
            "preferred_domain": official_domain,
            "max_results": max_results,
        })
        queries.append({
            "intent": "pricing",
            "query": f'site:{official_domain} "{tool_name}" pricing',
            "preferred_domain": official_domain,
            "max_results": max_results,
        })
    else:
        queries.append({
            "intent": "official",
            "query": f'"{tool_name}" official site',
            "preferred_domain": "",
            "max_results": max_results,
        })
        queries.append({
            "intent": "pricing",
            "query": f'"{tool_name}" pricing',
            "preferred_domain": "",
            "max_results": max_results,
        })

    review_domains = ["g2.com", "trustpilot.com", "trustradius.com", "capterra.com", "demandsage.com"]
    workflow_domains = ["zapier.com", "pcmag.com", "techradar.com", "youtube.com", "reddit.com"]
    alternative_domains = ["zapier.com", "pcmag.com", "techradar.com", "youtube.com", "reddit.com"]
    discussion_domains = ["reddit.com", "youtube.com"]

    for domain in review_domains:
        queries.append({
            "intent": "reviews",
            "query": f'site:{domain} "{tool_name}" review',
            "preferred_domain": domain,
            "max_results": max_results,
        })

    queries.append({
        "intent": "reviews",
        "query": f'"{tool_name}" reviews',
        "preferred_domain": "",
        "max_results": max_results,
    })

    for domain in workflow_domains:
        queries.append({
            "intent": "workflow",
            "query": f'site:{domain} "{tool_name}" review',
            "preferred_domain": domain,
            "max_results": max_results,
        })

    queries.append({
        "intent": "workflow",
        "query": f'"{tool_name}" workflow review',
        "preferred_domain": "",
        "max_results": max_results,
    })

    for domain in alternative_domains:
        queries.append({
            "intent": "alternatives",
            "query": f'site:{domain} "{tool_name}" alternatives',
            "preferred_domain": domain,
            "max_results": max_results,
        })

    queries.append({
        "intent": "alternatives",
        "query": f'"{tool_name}" alternatives',
        "preferred_domain": "",
        "max_results": max_results,
    })

    for domain in discussion_domains:
        queries.append({
            "intent": "discussions",
            "query": f'site:{domain} "{tool_name}"',
            "preferred_domain": domain,
            "max_results": max_results,
        })

    return queries


def fetch_duckduckgo_html(query: str) -> str:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def strip_tags(text: str) -> str:
    text = re.sub(r"<.*?>", "", text, flags=re.S)
    return html.unescape(normalize_whitespace(text))


def parse_duckduckgo_results(html_text: str, max_results: int) -> list[dict[str, str]]:
    patterns = [
        re.compile(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S),
        re.compile(r'<a[^>]+href="([^"]+)"[^>]+class="[^"]*result-link[^"]*"[^>]*>(.*?)</a>', re.I | re.S),
    ]

    matches: list[tuple[str, str]] = []
    for pattern in patterns:
        matches = pattern.findall(html_text)
        if matches:
            break

    results: list[dict[str, str]] = []
    seen = set()

    for href, raw_title in matches:
        resolved = decode_duckduckgo_redirect(html.unescape(href))
        if not resolved.startswith("http"):
            continue

        url = canonicalize_url(resolved)
        if url in seen:
            continue
        seen.add(url)

        title = strip_tags(raw_title)
        if not title:
            title = url

        results.append({
            "url": url,
            "title": title,
        })

        if len(results) >= max_results:
            break

    return results


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

    return {
        "url": url,
        "title": clean_string(title) or url,
        "domain": domain,
        "normalized_domain": normalized_domain,
        "source_kind": "webpage",
        "trust_tier": trust_tier,
        "source_role": classify_source_roles(intent, normalized_domain, official_domain),
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


def choose_primary_intent(record: dict[str, Any]) -> str:
    intents = record.get("intents", [])
    if not intents:
        return "reviews"

    priority = {
        "official": 1,
        "pricing": 2,
        "reviews": 3,
        "workflow": 4,
        "alternatives": 5,
        "discussions": 6,
    }
    return sorted(intents, key=lambda x: priority.get(x, 999))[0]


def select_sources(
    raw_sources: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    selected_urls = set()
    counts = {intent: 0 for intent in INTENT_CAPS}

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

    for record in sorted_sources:
        if record["trust_tier"] == 5:
            rejected_record = deepcopy(record)
            rejected_record["status"] = "rejected"
            rejected_record["selection_reason"] = "Rejected because the domain is low-trust or noisy."
            rejected.append(rejected_record)
            continue

        primary_intent = choose_primary_intent(record)
        cap = INTENT_CAPS.get(primary_intent, 0)

        if record["url"] in selected_urls:
            continue

        if counts.get(primary_intent, 0) >= cap:
            rejected_record = deepcopy(record)
            rejected_record["status"] = "rejected"
            rejected_record["selection_reason"] = f"Rejected because the {primary_intent} intent quota was already filled by stronger sources."
            rejected.append(rejected_record)
            continue

        selected_record = deepcopy(record)
        selected_record["status"] = "selected"
        selected_record["selection_reason"] = f"Selected as a high-trust source for {primary_intent} intent."
        selected.append(selected_record)
        selected_urls.add(selected_record["url"])
        counts[primary_intent] += 1

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
            html_text = fetch_duckduckgo_html(query)
            results = parse_duckduckgo_results(html_text, query_record["max_results"])
        except Exception as exc:
            warn(f"query failed for intent '{intent}': {query} ({exc})", warnings_list)
            continue

        for rank, result in enumerate(results, start=1):
            url = result["url"]
            title = result["title"]
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

    selected_sources, rejected_sources = select_sources(raw_sources)

    selected_by_intent = {intent: 0 for intent in INTENT_CAPS}
    for record in selected_sources:
        primary_intent = choose_primary_intent(record)
        selected_by_intent[primary_intent] += 1

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
