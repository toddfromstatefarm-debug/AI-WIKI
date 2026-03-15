#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


PREFERRED_SOURCE_MAP = {
    "g2.com": "G2 review",
    "trustpilot.com": "Trustpilot review",
    "trustradius.com": "TrustRadius review",
    "capterra.com": "Capterra review",
    "reddit.com": "Reddit thread",
    "youtube.com": "YouTube review",
    "demandsage.com": "DemandSage",
    "zapier.com": "Zapier review",
    "pcmag.com": "PCMag review",
    "techradar.com": "TechRadar review",
}

LOW_TRUST_OR_NOISY_DOMAINS = {
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

WEAK_SOURCE_LABELS = {
    "user review",
    "review",
    "blog",
    "article",
    "forum",
    "thread",
    "user discussion",
    "website",
    "company blog",
    "customer review",
    "source",
    "discussion",
    "video",
    "user feedback",
    "online review",
}

PLACEHOLDER_TEXT = {
    "tbd",
    "todo",
    "placeholder",
    "coming soon",
    "fill later",
    "to be added",
}

VALID_MONETIZATION_TYPES = {"affiliate", "partner", "official-link-only", "none"}
VALID_CONFIDENCE = {"low", "medium", "high"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a normalized tool draft JSON from source_input.json")
    parser.add_argument("--input", required=True, help="Path to source_input.json")
    parser.add_argument("--output", default="", help="Optional path to output draft JSON")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output file")
    return parser


def warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def is_placeholder_string(value: str) -> bool:
    normalized = normalize_whitespace(value).lower()
    return normalized in PLACEHOLDER_TEXT


def clean_string(value: object) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = normalize_whitespace(value)
    if cleaned and is_placeholder_string(cleaned):
        return ""
    return cleaned


def validate_slug(slug: str) -> bool:
    return re.fullmatch(r"[a-z0-9-]+", slug) is not None


def unique_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def normalize_string_list(value: object, max_items: int | None = None) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []

    cleaned: list[str] = []
    for item in values:
        text = clean_string(item)
        if text:
            cleaned.append(text)

    cleaned = unique_preserve_order(cleaned)

    if max_items is not None:
        cleaned = cleaned[:max_items]

    return cleaned


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


def is_low_trust_domain(domain: str) -> bool:
    return domain in LOW_TRUST_OR_NOISY_DOMAINS


def is_weak_source_label(label: str) -> bool:
    normalized = normalize_whitespace(label).lower()
    if normalized == "":
        return True
    return normalized in WEAK_SOURCE_LABELS


def humanize_domain_label(domain: str) -> str:
    if not domain:
        return "Source"

    root = domain.split(".")[0]
    root = root.replace("-", " ").replace("_", " ")
    root = re.sub(r"\s+", " ", root).strip()
    if not root:
        return "Source"
    return f"{root.title()} review"


def normalize_source_label(existing_label: str, link: str) -> str:
    domain = extract_registered_domain(link)
    existing = clean_string(existing_label)

    if domain in PREFERRED_SOURCE_MAP:
        preferred = PREFERRED_SOURCE_MAP[domain]
        if existing != preferred:
            warn(f"recurring_signals quote source label normalized from preferred domain '{domain}' to '{preferred}'.")
        return preferred

    if existing and not is_weak_source_label(existing):
        if domain and is_low_trust_domain(domain):
            warn(f"recurring_signals quote domain appears low-trust or noisy: {domain}.")
        return existing

    if domain:
        fallback = humanize_domain_label(domain)
        if existing:
            warn(f"recurring_signals quote source label normalized from weak label '{existing}' to '{fallback}'.")
        if is_low_trust_domain(domain):
            warn(f"recurring_signals quote domain appears low-trust or noisy: {domain}.")
        return fallback

    return existing or "Source"


def normalize_quote(quote: object) -> dict | None:
    if not isinstance(quote, dict):
        return None

    text = clean_string(quote.get("text", ""))
    if not text:
        warn("recurring_signals quote dropped: missing text.")
        return None

    link = clean_string(quote.get("link", ""))
    if not link:
        warn("recurring_signals quote dropped: missing link.")
        return None

    source = normalize_source_label(str(quote.get("source", "")), link)

    return {
        "text": text,
        "source": source,
        "link": link,
    }


def normalize_recurring_signal(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None

    theme = clean_string(item.get("theme", ""))
    if not theme:
        warn("recurring_signals item dropped: missing theme.")
        return None

    descriptor = clean_string(item.get("descriptor", ""))
    if not descriptor:
        warn("recurring_signals item dropped: missing descriptor.")
        return None

    praise_quotes_raw = item.get("praise_quotes", [])
    critique_quotes_raw = item.get("critique_quotes", [])

    praise_quotes = []
    if isinstance(praise_quotes_raw, list):
        for quote in praise_quotes_raw:
            normalized = normalize_quote(quote)
            if normalized:
                praise_quotes.append(normalized)
    praise_quotes = praise_quotes[:3]

    critique_quotes = []
    if isinstance(critique_quotes_raw, list):
        for quote in critique_quotes_raw:
            normalized = normalize_quote(quote)
            if normalized:
                critique_quotes.append(normalized)
    critique_quotes = critique_quotes[:3]

    if not praise_quotes and not critique_quotes:
        warn("recurring_signals item dropped: no valid praise_quotes or critique_quotes.")
        return None

    disagreement = clean_string(item.get("disagreement", ""))
    fit_implication = clean_string(item.get("fit_implication", ""))

    return {
        "theme": theme,
        "descriptor": descriptor,
        "praise_quotes": praise_quotes,
        "critique_quotes": critique_quotes,
        "disagreement": disagreement,
        "fit_implication": fit_implication,
    }


def normalize_pricing_tier(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None

    tier = clean_string(item.get("tier", ""))
    price = clean_string(item.get("price", ""))
    features = normalize_string_list(item.get("features", []))

    if not tier and not price and not features:
        return None

    return {
        "tier": tier,
        "price": price,
        "features": features,
    }


def normalize_typical_alternative(item: object) -> dict | None:
    if not isinstance(item, dict):
        warn("typical_alternatives item dropped: missing name, difference, or best_for.")
        return None

    name = clean_string(item.get("name", ""))
    difference = clean_string(item.get("difference", ""))
    best_for = clean_string(item.get("best_for", ""))

    if not name or not difference or not best_for:
        warn("typical_alternatives item dropped: missing name, difference, or best_for.")
        return None

    return {
        "name": name,
        "difference": difference,
        "best_for": best_for,
    }


def normalize_workflow_insights(value: object) -> dict:
    blank = {"narrative": "", "tradeoffs": []}

    if not isinstance(value, dict):
        warn("workflow_insights missing or empty; workflow_insights will be blank.")
        return blank

    narrative = clean_string(value.get("narrative", ""))
    tradeoffs = normalize_string_list(value.get("tradeoffs", []), max_items=4)

    if not narrative and not tradeoffs:
        warn("workflow_insights missing or empty; workflow_insights will be blank.")
        return blank

    return {
        "narrative": narrative,
        "tradeoffs": tradeoffs,
    }


def normalize_illustrative_output(value: object) -> dict:
    blank = {"prompt": "", "sample_output": "", "interpretation": ""}

    if not isinstance(value, dict):
        return blank

    prompt = clean_string(value.get("prompt", ""))
    sample_output = clean_string(value.get("sample_output", ""))
    interpretation = clean_string(value.get("interpretation", ""))

    if prompt and sample_output and interpretation:
        lowered = " ".join([prompt.lower(), sample_output.lower(), interpretation.lower()])
        if any(flag in lowered for flag in ["we tested", "benchmark", "verified output", "measured result"]):
            warn("illustrative_output contains testing-like language; review trust framing manually.")
        return {
            "prompt": prompt,
            "sample_output": sample_output,
            "interpretation": interpretation,
        }

    if prompt or sample_output or interpretation:
        warn("illustrative_output incomplete; clearing illustrative_output.")

    return blank


def normalize_overview(value: object) -> list[str]:
    paragraphs: list[str] = []

    if isinstance(value, str):
        text = clean_string(value)
        if text:
            paragraphs = [text]
    elif isinstance(value, list):
        for item in value:
            text = clean_string(item)
            if text:
                paragraphs.append(text)
            else:
                if isinstance(item, str) and item.strip():
                    warn("overview paragraph dropped: empty or placeholder text.")
    else:
        paragraphs = []

    cleaned = []
    for paragraph in paragraphs:
        if is_placeholder_string(paragraph):
            warn("overview paragraph dropped: empty or placeholder text.")
            continue
        cleaned.append(paragraph)

    cleaned = cleaned[:4]

    if not cleaned:
        fail("overview is empty after normalization.")

    return cleaned


def resolve_logo_url(source_input: dict) -> str:
    logo_url = clean_string(source_input.get("logo_url", ""))
    logo_path = clean_string(source_input.get("logo_path", ""))

    if logo_url:
        return logo_url

    if logo_path:
        warn("logo_path provided without logo_url; using logo_path as logo_url.")
        return logo_path

    return ""


def resolve_affiliate_link(source_input: dict, official_url: str, quick_pros: list[str], quick_cons: list[str], verdict_confidence: str) -> str:
    monetization_type = clean_string(source_input.get("monetization_type", ""))
    affiliate_link = clean_string(source_input.get("affiliate_link", ""))

    if monetization_type == "affiliate":
        if not affiliate_link:
            warn("monetization_type is affiliate but affiliate_link is blank.")
    elif monetization_type == "none":
        if affiliate_link:
            warn("monetization_type is none but affiliate_link was provided; clearing affiliate_link.")
        affiliate_link = ""
    elif monetization_type == "official-link-only":
        if not affiliate_link:
            affiliate_link = official_url

    if not quick_pros and not quick_cons and not verdict_confidence and affiliate_link:
        warn("affiliate_link suppressed because Quick Verdict has no supporting content and the current template would render an empty verdict shell.")
        affiliate_link = ""

    return affiliate_link


def require_string_field(data: dict, field_name: str) -> str:
    value = clean_string(data.get(field_name, ""))
    if not value:
        fail(f"missing required field: {field_name}")
    return value


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        fail(f"input file not found: {input_path}")

    with input_path.open("r", encoding="utf-8") as f:
        source_input = json.load(f)

    tool_name = require_string_field(source_input, "tool_name")
    slug = require_string_field(source_input, "slug")
    tagline = require_string_field(source_input, "tagline")
    official_url = require_string_field(source_input, "official_url")
    monetization_type = require_string_field(source_input, "monetization_type")

    if not validate_slug(slug):
        fail("slug must contain only lowercase letters, numbers, and hyphens.")

    if monetization_type not in VALID_MONETIZATION_TYPES:
        fail("monetization_type must be one of: affiliate, partner, official-link-only, none.")

    if "overview" not in source_input:
        fail("missing required field: overview")

    last_updated = clean_string(source_input.get("last_updated", ""))
    if not last_updated:
        last_updated = date.today().isoformat()
        warn(f"last_updated missing; using today's date {last_updated}.")

    pricing_notes = source_input.get("pricing_notes", [])
    pricing_tiers: list[dict] = []
    if isinstance(pricing_notes, list):
        for item in pricing_notes:
            normalized = normalize_pricing_tier(item)
            if normalized:
                pricing_tiers.append(normalized)
    if not pricing_tiers:
        warn("pricing_notes missing or empty; pricing_tiers will be empty.")

    quick_pros = normalize_string_list(source_input.get("quick_pros", []), max_items=5)
    quick_cons = normalize_string_list(source_input.get("quick_cons", []), max_items=5)

    verdict_confidence_suggested = clean_string(source_input.get("verdict_confidence_suggested", "")).lower()
    if verdict_confidence_suggested in VALID_CONFIDENCE:
        verdict_confidence = verdict_confidence_suggested
    else:
        verdict_confidence = ""
        warn("verdict_confidence_suggested missing or invalid; leaving verdict_confidence blank.")

    signal_sources_raw = source_input.get("signal_sources", [])
    signal_source_categories = normalize_string_list(signal_sources_raw, max_items=5)
    if not signal_source_categories:
        warn("signal_sources missing or empty; signal_sources.categories will be empty.")

    recurring_signals_raw = source_input.get("recurring_signals", [])
    recurring_signals: list[dict] = []
    if isinstance(recurring_signals_raw, list):
        for item in recurring_signals_raw:
            normalized = normalize_recurring_signal(item)
            if normalized:
                recurring_signals.append(normalized)
    recurring_signals = recurring_signals[:4]

    best_fit = normalize_string_list(source_input.get("best_fit", []), max_items=3)
    if not best_fit:
        warn("best_fit missing or empty; section will remain hidden.")

    not_ideal_for = normalize_string_list(source_input.get("not_ideal_for", []), max_items=3)
    if not not_ideal_for:
        warn("not_ideal_for missing or empty; section will remain hidden.")

    alternatives_raw = source_input.get("typical_alternatives", [])
    typical_alternatives: list[dict] = []
    if isinstance(alternatives_raw, list):
        for item in alternatives_raw:
            normalized = normalize_typical_alternative(item)
            if normalized:
                typical_alternatives.append(normalized)
    typical_alternatives = typical_alternatives[:4]

    workflow_insights = normalize_workflow_insights(source_input.get("workflow_insights", {}))
    illustrative_output = normalize_illustrative_output(source_input.get("illustrative_output", {}))
    overview = normalize_overview(source_input.get("overview"))

    logo_url = resolve_logo_url(source_input)
    affiliate_link = resolve_affiliate_link(
        source_input=source_input,
        official_url=official_url,
        quick_pros=quick_pros,
        quick_cons=quick_cons,
        verdict_confidence=verdict_confidence,
    )

    draft = {
        "slug": slug,
        "layout": "tool",
        "tool_name": tool_name,
        "tagline": tagline,
        "logo_url": logo_url,
        "official_url": official_url,
        "monetization_type": monetization_type,
        "pricing_tiers": pricing_tiers,
        "last_updated": last_updated,
        "quick_pros": quick_pros,
        "quick_cons": quick_cons,
        "verdict_confidence": verdict_confidence,
        "affiliate_link": affiliate_link,
        "signal_sources": {
            "categories": signal_source_categories
        },
        "recurring_signals": recurring_signals,
        "best_fit": best_fit,
        "not_ideal_for": not_ideal_for,
        "typical_alternatives": typical_alternatives,
        "workflow_insights": workflow_insights,
        "illustrative_output": illustrative_output,
        "overview": overview,
    }

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path("automation") / "drafts" / f"{slug}.draft.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and not args.force:
        fail(f"output file already exists: {output_path} (use --force to overwrite)")

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(draft, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote draft: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
