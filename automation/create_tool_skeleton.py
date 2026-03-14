#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a new tool page skeleton, image folder, and directory entry."
    )
    parser.add_argument("--tool-name", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--tagline", default="")
    parser.add_argument("--official-url", default="")
    parser.add_argument(
        "--monetization-type",
        default="",
        choices=["", "affiliate", "partner", "official-link-only", "none"],
    )
    parser.add_argument("--affiliate-link", default="")
    parser.add_argument("--force", action="store_true")
    return parser


def yaml_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def validate_slug(slug: str) -> bool:
    return re.fullmatch(r"[a-z0-9-]+", slug) is not None


def resolve_affiliate_link(affiliate_link: str, official_url: str, monetization_type: str) -> str:
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


def build_directory_entry(tool_name: str, slug: str, tagline: str) -> str:
    link = f"- [{tool_name}]({{{{ '/tools/{slug}.html' | relative_url }}}})"
    cleaned_tagline = tagline.strip()
    if cleaned_tagline:
        return f"{link} – {cleaned_tagline}"
    return link


def directory_entry_exists(directory_text: str, slug: str) -> bool:
    target = f"{{{{ '/tools/{slug}.html' | relative_url }}}}"
    return target in directory_text


def main() -> int:
    args = build_parser().parse_args()

    if not validate_slug(args.slug):
        print("Error: slug must contain only lowercase letters, numbers, and hyphens.", file=sys.stderr)
        return 1

    repo_root = Path.cwd()
    tools_dir = repo_root / "tools"
    assets_dir = repo_root / "assets" / "images" / "tools" / args.slug
    tool_file = tools_dir / f"{args.slug}.md"
    directory_file = repo_root / "directory.md"

    if not tools_dir.exists():
        print(f"Error: expected tools directory at {tools_dir} but it does not exist.", file=sys.stderr)
        return 1

    if not directory_file.exists():
        print(f"Error: expected directory file at {directory_file} but it does not exist.", file=sys.stderr)
        return 1

    if tool_file.exists() and not args.force:
        print(f"Error: {tool_file} already exists. Use --force to overwrite it.", file=sys.stderr)
        return 1

    resolved_affiliate_link = resolve_affiliate_link(
        affiliate_link=args.affiliate_link,
        official_url=args.official_url,
        monetization_type=args.monetization_type,
    )

    if args.monetization_type == "affiliate" and not resolved_affiliate_link:
        print("Warning: monetization_type is affiliate but no affiliate_link was provided.", file=sys.stderr)

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

    directory_text = directory_file.read_text(encoding="utf-8")
    directory_updated = False

    if not directory_entry_exists(directory_text, args.slug.strip()):
        entry = build_directory_entry(
            tool_name=args.tool_name.strip(),
            slug=args.slug.strip(),
            tagline=args.tagline.strip(),
        )
        content = directory_text.rstrip()
        if content:
            content += "\n" + entry + "\n"
        else:
            content = entry + "\n"
        directory_file.write_text(content, encoding="utf-8", newline="\n")
        directory_updated = True

    print(f"Created: {tool_file}")
    print(f"Created folder: {assets_dir}")
    if directory_updated:
        print(f"Appended directory entry to: {directory_file}")
    else:
        print(f"Directory entry already exists in: {directory_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
