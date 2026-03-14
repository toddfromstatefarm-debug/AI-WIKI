#!/usr/bin/env python3
"""
Create a new tool page skeleton using the current Jasper-based schema.

Usage:
    python automation/create_tool_skeleton.py --tool-name "Writesonic" --slug "writesonic"

Optional:
    python automation/create_tool_skeleton.py \
        --tool-name "Writesonic" \
        --slug "writesonic" \
        --tagline "AI writing and marketing content platform" \
        --official-url "https://writesonic.com/" \
        --monetization-type "official-link-only" \
        --affiliate-link "https://writesonic.com/" \
        --force
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a new tool page skeleton and image folder."
    )
    parser.add_argument(
        "--tool-name",
        required=True,
        help='Public tool name, e.g. "Writesonic"',
    )
    parser.add_argument(
        "--slug",
        required=True,
        help='URL/file slug, e.g. "writesonic"',
    )
    parser.add_argument(
        "--tagline",
        default="",
        help="Optional one-line tagline",
    )
    parser.add_argument(
        "--official-url",
        default="",
        help="Optional official product URL",
    )
    parser.add_argument(
        "--monetization-type",
        default="",
        choices=["", "affiliate", "partner", "official-link-only", "none"],
        help='Optional monetization type: "", affiliate, partner, official-link-only, none',
    )
    parser.add_argument(
        "--affiliate-link",
        default="",
        help="Optional affiliate or official CTA URL",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing tool markdown file if it already exists",
    )
    return parser


def yaml_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def validate_slug(slug: str) -> bool:
    return re.fullmatch(r"[a-z0-9-]+", slug) is not None


def resolve_affiliate_link(
    affiliate_link: str,
    official_url: str,
    monetization_type: str,
) -> str:
    if affiliate_link.strip():
        return affiliate_link.strip()

    if monetization_type == "official-link-only" and official_url.strip():
        return official_url.strip()

    return ""


def build_markdown(
    tool_name: str,
    tagline: str,
    official_url: str,
    monetization_type: str,
    affiliate_link: str,
    today: str,
) -> str:
    lines = [
        "---",
        "layout: tool",
        f"tool_name: {yaml_escape(tool_name)}",
        f"tagline: {yaml_escape(tagline)}",
        'logo_url: ""',
        f"official_url: {yaml_escape(official_url)}",
        f"monetization_type: {yaml_escape(monetization_type)}",
        "pricing_tiers: []",
        f"last_updated: {yaml_escape(today)}",
        "quick_pros: []",
        "quick_cons: []",
        'verdict_confidence: ""',
        f"affiliate_link: {yaml_escape(affiliate_link)}",
        "signal_sources:",
        "  categories: []",
        "recurring_signals: []",
        "best_fit: []",
        "not_ideal_for: []",
        "typical_alternatives: []",
        "workflow_insights: {}",
        "illustrative_output: {}",
        "---",
        "",
        "<h2>Overview</h2>",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    args = build_parser().parse_args()

    if not validate_slug(args.slug):
        print(
            "Error: slug must contain only lowercase letters, numbers, and hyphens.",
            file=sys.stderr,
        )
        return 1

    repo_root = Path.cwd()
    tools_dir = repo_root / "tools"
    assets_dir = repo_root / "assets" / "images" / "tools" / args.slug
    tool_file = tools_dir / f"{args.slug}.md"

    if not tools_dir.exists():
        print(
            f"Error: expected tools directory at {tools_dir} but it does not exist.",
            file=sys.stderr,
        )
        return 1

    if tool_file.exists() and not args.force:
        print(
            f"Error: {tool_file} already exists. Use --force to overwrite it.",
            file=sys.stderr,
        )
        return 1

    resolved_affiliate_link = resolve_affiliate_link(
        affiliate_link=args.affiliate_link,
        official_url=args.official_url,
        monetization_type=args.monetization_type,
    )

    if args.monetization_type == "affiliate" and not resolved_affiliate_link:
        print(
            "Warning: monetization_type is affiliate but no affiliate_link was provided.",
            file=sys.stderr,
        )

    today = date.today().isoformat()

    markdown = build_markdown(
        tool_name=args.tool_name.strip(),
        tagline=args.tagline.strip(),
        official_url=args.official_url.strip(),
        monetization_type=args.monetization_type.strip(),
        affiliate_link=resolved_affiliate_link,
        today=today,
    )

    assets_dir.mkdir(parents=True, exist_ok=True)
    tool_file.write_text(markdown, encoding="utf-8", newline="\n")

    print(f"Created: {tool_file}")
    print(f"Created folder: {assets_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
