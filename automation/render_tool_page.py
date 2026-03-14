#!/usr/bin/env python3
"""
render_tool_page.py

AI Decision Hub - Tool Page Renderer (v1)

Converts:
  automation/drafts/<slug>.draft.json
into:
  tools/<slug>.md

Requirements:
- Overwrite only with --force
- Preserve fixed Jasper-mold front matter field order
- Always write stable schema keys (fail-closed; empty arrays/objects are allowed)
- Write body as:
    <h2>Overview</h2>
    + overview paragraphs from draft.json["overview"]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional


SLUG_RE = re.compile(r"^[a-z0-9-]+$")

# Exact front matter key order (top-level)
FRONT_MATTER_ORDER: List[str] = [
    "layout",
    "tool_name",
    "tagline",
    "logo_url",
    "official_url",
    "monetization_type",
    "pricing_tiers",
    "last_updated",
    "quick_pros",
    "quick_cons",
    "verdict_confidence",
    "affiliate_link",
    "signal_sources",
    "recurring_signals",
    "best_fit",
    "not_ideal_for",
    "typical_alternatives",
    "workflow_insights",
    "illustrative_output",
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Render a tool markdown page from automation/drafts/<slug>.draft.json"
    )
    p.add_argument("--slug", required=True, help='Tool slug, e.g. "notion"')
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite tools/<slug>.md if it already exists",
    )
    p.add_argument(
        "--drafts-dir",
        default="automation/drafts",
        help='Drafts directory (default: "automation/drafts")',
    )
    p.add_argument(
        "--tools-dir",
        default="tools",
        help='Tools directory (default: "tools")',
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress success output",
    )
    return p


def die(msg: str, code: int = 1) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return code


def warn(msg: str) -> None:
    print(f"Warning: {msg}", file=sys.stderr)


def validate_slug(slug: str) -> bool:
    return SLUG_RE.fullmatch(slug) is not None


def read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Draft JSON must be an object at the top level.")
    return data


def coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def coerce_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def coerce_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def yaml_quote(s: str) -> str:
    """
    YAML double-quoted string with minimal escaping.
    """
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\n", "\\n")
    return f'"{s}"'


def emit_list_of_strings(key: str, items: List[Any], indent: int = 0) -> List[str]:
    pad = " " * indent
    clean: List[str] = []
    for it in items:
        if isinstance(it, str) and it != "":
            clean.append(it)

    if not clean:
        return [f"{pad}{key}: []"]

    lines = [f"{pad}{key}:"]
    for s in clean:
        lines.append(f"{pad}  - {yaml_quote(s)}")
    return lines


def emit_signal_sources(obj: Dict[str, Any], indent: int = 0) -> List[str]:
    pad = " " * indent
    categories = coerce_list(obj.get("categories"))
    lines = [f"{pad}signal_sources:"]
    sub = emit_list_of_strings("categories", categories, indent=indent + 2)
    lines.extend(sub)
    return lines


def emit_pricing_tiers(value: Any, indent: int = 0) -> List[str]:
    pad = " " * indent
    tiers = coerce_list(value)
    if not tiers:
        return [f"{pad}pricing_tiers: []"]

    lines = [f"{pad}pricing_tiers:"]
    for t in tiers:
        tdict = coerce_dict(t)
        tier = coerce_str(tdict.get("tier"))
        price = coerce_str(tdict.get("price"))
        features = coerce_list(tdict.get("features"))

        lines.append(f"{pad}  - tier: {yaml_quote(tier)}")
        lines.append(f"{pad}    price: {yaml_quote(price)}")
        if not features:
            lines.append(f"{pad}    features: []")
        else:
            lines.append(f"{pad}    features:")
            for f in features:
                if isinstance(f, str) and f != "":
                    lines.append(f"{pad}      - {yaml_quote(f)}")
    return lines


def emit_quote_list(key: str, quotes: Any, indent: int = 0) -> List[str]:
    pad = " " * indent
    qlist = coerce_list(quotes)
    if not qlist:
        return [f"{pad}{key}: []"]

    lines = [f"{pad}{key}:"]
    for q in qlist:
        qd = coerce_dict(q)
        text = coerce_str(qd.get("text"))
        source = coerce_str(qd.get("source"))
        link = coerce_str(qd.get("link"))
        lines.append(f"{pad}  - text: {yaml_quote(text)}")
        lines.append(f"{pad}    source: {yaml_quote(source)}")
        lines.append(f"{pad}    link: {yaml_quote(link)}")
    return lines


def emit_recurring_signals(value: Any, indent: int = 0) -> List[str]:
    pad = " " * indent
    items = coerce_list(value)
    if not items:
        return [f"{pad}recurring_signals: []"]

    lines = [f"{pad}recurring_signals:"]
    for it in items:
        d = coerce_dict(it)
        theme = coerce_str(d.get("theme"))
        descriptor = coerce_str(d.get("descriptor"))
        disagreement = coerce_str(d.get("disagreement"))
        fit_implication = coerce_str(d.get("fit_implication"))

        lines.append(f"{pad}  - theme: {yaml_quote(theme)}")
        lines.append(f"{pad}    descriptor: {yaml_quote(descriptor)}")

        lines.extend(emit_quote_list("praise_quotes", d.get("praise_quotes"), indent=indent + 4))
        lines.extend(emit_quote_list("critique_quotes", d.get("critique_quotes"), indent=indent + 4))

        lines.append(f"{pad}    disagreement: {yaml_quote(disagreement)}")
        lines.append(f"{pad}    fit_implication: {yaml_quote(fit_implication)}")

    return lines


def emit_typical_alternatives(value: Any, indent: int = 0) -> List[str]:
    pad = " " * indent
    items = coerce_list(value)
    if not items:
        return [f"{pad}typical_alternatives: []"]

    lines = [f"{pad}typical_alternatives:"]
    for it in items:
        d = coerce_dict(it)
        name = coerce_str(d.get("name"))
        diff = coerce_str(d.get("difference"))
        best_for = coerce_str(d.get("best_for"))

        lines.append(f"{pad}  - name: {yaml_quote(name)}")
        lines.append(f"{pad}    difference: {yaml_quote(diff)}")
        lines.append(f"{pad}    best_for: {yaml_quote(best_for)}")
    return lines


def emit_workflow_insights(value: Any, indent: int = 0) -> List[str]:
    pad = " " * indent
    d = coerce_dict(value)
    narrative = coerce_str(d.get("narrative"))
    tradeoffs = coerce_list(d.get("tradeoffs"))

    lines = [f"{pad}workflow_insights:"]
    lines.append(f"{pad}  narrative: {yaml_quote(narrative)}")
    lines.extend(emit_list_of_strings("tradeoffs", tradeoffs, indent=indent + 2))
    return lines


def emit_illustrative_output(value: Any, indent: int = 0) -> List[str]:
    pad = " " * indent
    d = coerce_dict(value)
    prompt = coerce_str(d.get("prompt"))
    sample_output = coerce_str(d.get("sample_output"))
    interpretation = coerce_str(d.get("interpretation"))

    lines = [f"{pad}illustrative_output:"]
    lines.append(f"{pad}  prompt: {yaml_quote(prompt)}")
    lines.append(f"{pad}  sample_output: {yaml_quote(sample_output)}")
    lines.append(f"{pad}  interpretation: {yaml_quote(interpretation)}")
    return lines


def build_front_matter(draft: Dict[str, Any]) -> str:
    layout = coerce_str(draft.get("layout")) or "tool"
    tool_name = coerce_str(draft.get("tool_name"))
    tagline = coerce_str(draft.get("tagline"))
    logo_url = coerce_str(draft.get("logo_url"))
    official_url = coerce_str(draft.get("official_url"))
    monetization_type = coerce_str(draft.get("monetization_type"))

    last_updated = coerce_str(draft.get("last_updated"))
    if not last_updated:
        last_updated = date.today().isoformat()
        warn(f"last_updated missing in draft; defaulted to {last_updated}.")

    verdict_confidence = coerce_str(draft.get("verdict_confidence"))
    affiliate_link = coerce_str(draft.get("affiliate_link"))

    lines: List[str] = ["---"]
    lines.append(f"layout: {layout}")
    lines.append(f"tool_name: {yaml_quote(tool_name)}")
    lines.append(f"tagline: {yaml_quote(tagline)}")
    lines.append(f"logo_url: {yaml_quote(logo_url)}")
    lines.append(f"official_url: {yaml_quote(official_url)}")
    lines.append(f"monetization_type: {yaml_quote(monetization_type)}")
    lines.extend(emit_pricing_tiers(draft.get("pricing_tiers"), indent=0))
    lines.append(f"last_updated: {yaml_quote(last_updated)}")
    lines.extend(emit_list_of_strings("quick_pros", coerce_list(draft.get("quick_pros")), indent=0))
    lines.extend(emit_list_of_strings("quick_cons", coerce_list(draft.get("quick_cons")), indent=0))
    lines.append(f"verdict_confidence: {yaml_quote(verdict_confidence)}")
    lines.append(f"affiliate_link: {yaml_quote(affiliate_link)}")
    lines.extend(emit_signal_sources(coerce_dict(draft.get("signal_sources")), indent=0))
    lines.extend(emit_recurring_signals(draft.get("recurring_signals"), indent=0))
    lines.extend(emit_list_of_strings("best_fit", coerce_list(draft.get("best_fit")), indent=0))
    lines.extend(emit_list_of_strings("not_ideal_for", coerce_list(draft.get("not_ideal_for")), indent=0))
    lines.extend(emit_typical_alternatives(draft.get("typical_alternatives"), indent=0))
    lines.extend(emit_workflow_insights(draft.get("workflow_insights"), indent=0))
    lines.extend(emit_illustrative_output(draft.get("illustrative_output"), indent=0))
    lines.append("---")
    return "\n".join(lines) + "\n"


def build_body(draft: Dict[str, Any]) -> str:
    overview = coerce_str(draft.get("overview"))
    overview = overview.replace("\r\n", "\n").replace("\r", "\n").strip()

    parts: List[str] = ["<h2>Overview</h2>", ""]

    if overview:
        paras = re.split(r"\n\s*\n+", overview)
        cleaned: List[str] = []
        for p in paras:
            p2 = p.strip()
            if p2:
                cleaned.append(p2)
        if cleaned:
            parts.append("\n\n".join(cleaned))
            parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    args = build_parser().parse_args()
    slug = args.slug.strip()

    if not slug:
        return die("slug must not be blank.")
    if not validate_slug(slug):
        return die("slug must contain only lowercase letters, numbers, and hyphens.")

    repo_root = Path.cwd()
    drafts_dir = repo_root / args.drafts_dir
    tools_dir = repo_root / args.tools_dir

    draft_path = drafts_dir / f"{slug}.draft.json"
    out_path = tools_dir / f"{slug}.md"

    if not tools_dir.exists():
        return die(f"tools directory not found: {tools_dir}")

    try:
        draft = read_json(draft_path)
    except FileNotFoundError:
        return die(f"draft file not found: {draft_path}")
    except ValueError as e:
        return die(str(e))

    if out_path.exists() and not args.force:
        return die(f"output already exists: {out_path} (use --force to overwrite)")

    tool_name = coerce_str(draft.get("tool_name")).strip()
    if not tool_name:
        return die("draft.json is missing tool_name (required).")

    front_matter = build_front_matter(draft)
    body = build_body(draft)
    content = front_matter + "\n" + body

    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8", newline="\n")
    tmp_path.replace(out_path)

    if not args.quiet:
        print(f"Rendered: {out_path}")
        print(f"From: {draft_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
