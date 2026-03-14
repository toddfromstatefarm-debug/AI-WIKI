#!/usr/bin/env python3
"""
prepare_tool_draft.py

AI Decision Hub - prepare_tool_draft.py (v1)

Transforms a manually prepared source_input.json into a normalized draft.json that matches the
current Jasper-mold tool page schema.

v1 goals:
- Deterministic: no autonomous research, no content invention.
- Fail-closed: if staged input is incomplete, output empty arrays/objects/strings so the current
  Jekyll guards keep sections hidden.
- Template-aware: suppress content that would render empty shells under the current includes.

Run from the repository root (recommended):

    python automation/prepare_tool_draft.py --input automation/source_inputs/clickup.json

Default output (if --output omitted):
    automation/drafts/<slug>.draft.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# -------------------------
# Logging
# -------------------------

@dataclass
class Log:
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"Warning: {msg}", file=sys.stderr)

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        print(f"Error: {msg}", file=sys.stderr)

    def has_errors(self) -> bool:
        return bool(self.errors)


# -------------------------
# CLI
# -------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Convert source_input.json into draft.json (AI Decision Hub Page Formula v1)."
    )
    p.add_argument("--input", required=True, help="Path to source_input.json")
    p.add_argument(
        "--output",
        default="",
        help="Optional output path. If omitted, writes to automation/drafts/<slug>.draft.json",
    )
    p.add_argument("--force", action="store_true", help="Overwrite output if it already exists")
    p.add_argument("--quiet", action="store_true", help="Suppress success message")
    return p


# -------------------------
# Constants
# -------------------------

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_WS_RE = re.compile(r"\s+")
_TESTY_PHRASES_RE = re.compile(
    r"\b(we tested|we ran|benchmark|benchmarked|measured result|measured results|verified test|formal test)\b",
    re.IGNORECASE,
)

_ALLOWED_MONETIZATION = {"affiliate", "partner", "official-link-only", "none", ""}
_ALLOWED_CONFIDENCE = {"low", "medium", "high"}

_LEFT_QUOTES = {'"', "“", "‘", "'"}
_RIGHT_QUOTES = {'"', "”", "’", "'"}


# -------------------------
# Helpers
# -------------------------

def validate_slug(slug: str) -> bool:
    return _SLUG_RE.fullmatch(slug) is not None


def is_http_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def normalize_whitespace(text: str) -> str:
    return _WS_RE.sub(" ", text.strip())


def strip_wrapping_quotes(text: str) -> str:
    if not text:
        return text
    t = text.strip()
    if len(t) >= 2 and t[0] in _LEFT_QUOTES and t[-1] in _RIGHT_QUOTES:
        return t[1:-1].strip()
    return t


def normalize_string(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return normalize_whitespace(value)


def dedupe_strings(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for s in items:
        key = s.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def normalize_string_list(
    value: Any,
    *,
    max_items: int,
    min_chars: int = 0,
    strip_quotes: bool = False,
) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []

    out: List[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        s = normalize_whitespace(item)
        if strip_quotes:
            s = strip_wrapping_quotes(s)
        if not s:
            continue
        if min_chars and len(s) < min_chars:
            continue
        out.append(s)

    out = dedupe_strings(out)
    if len(out) > max_items:
        out = out[:max_items]
    return out


def normalize_confidence(value: Any) -> str:
    s = normalize_string(value).lower()
    if s in ("med", "moderate"):
        s = "medium"
    return s if s in _ALLOWED_CONFIDENCE else ""


def normalize_last_updated(value: Any, log: Log) -> str:
    s = normalize_string(value)
    today = date.today().isoformat()

    if not s:
        log.warn(f"W002 last_updated missing; defaulted to {today}.")
        return today

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s

    log.warn(f"W002 last_updated invalid ({s}); defaulted to {today}.")
    return today


def resolve_logo_url(source: Dict[str, Any], log: Log) -> str:
    candidate = normalize_string(source.get("logo_url")) or normalize_string(source.get("logo_path"))
    if not candidate:
        return ""

    if is_http_url(candidate):
        log.warn("W004 logo_url/logo_path is an external URL; blanked because the template uses relative_url.")
        return ""

    if candidate.startswith("assets/"):
        candidate = "/" + candidate

    if candidate.startswith("/assets/"):
        return candidate

    log.warn("W004 logo_url/logo_path is not a site-relative /assets/... path; blanked to avoid broken rendering.")
    return ""


def normalize_pricing_tiers(value: Any, log: Log) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        log.warn("W017 pricing_notes is not a list; dropped.")
        return []

    tiers: List[Dict[str, Any]] = []
    dropped = 0

    for item in value:
        if not isinstance(item, dict):
            dropped += 1
            continue

        tier = normalize_string(item.get("tier"))
        price = normalize_string(item.get("price"))
        features = normalize_string_list(item.get("features"), max_items=12, min_chars=2, strip_quotes=True)

        if not tier or not price or not features:
            dropped += 1
            continue

        tiers.append({"tier": tier, "price": price, "features": features})

    if dropped:
        log.warn(f"W017 pricing_notes had {dropped} invalid item(s) dropped.")

    return tiers


def resolve_affiliate_link(
    source: Dict[str, Any],
    monetization_type: str,
    official_url: str,
    log: Log,
) -> str:
    raw = normalize_string(source.get("affiliate_link"))
    if raw:
        if is_http_url(raw):
            return raw
        log.warn("W006 affiliate_link is not a valid http(s) URL; blanked.")
        return ""

    if monetization_type == "official-link-only":
        return official_url if is_http_url(official_url) else ""

    return ""


def normalize_overview(value: Any, log: Log) -> str:
    paragraphs: List[str] = []

    if value is None:
        return ""

    if isinstance(value, list):
        for p in value:
            if isinstance(p, str):
                s = normalize_whitespace(p)
                if s:
                    paragraphs.append(s)
    elif isinstance(value, str):
        s = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if s:
            raw_paras = re.split(r"\n\s*\n+", s)
            for p in raw_paras:
                s2 = normalize_whitespace(p)
                if s2:
                    paragraphs.append(s2)
    else:
        return ""

    if not paragraphs:
        return ""

    if len(paragraphs) > 4:
        log.warn("W015 Overview had more than 4 paragraphs; truncated to first 4.")
        paragraphs = paragraphs[:4]

    if len(paragraphs) < 2:
        log.warn("W016 Overview has fewer than 2 paragraphs; published pages should use 2–4 paragraphs.")

    return "\n\n".join(paragraphs)


# -------------------------
# Drop/keep rules for complex sections
# -------------------------

def build_quick_verdict(source: Dict[str, Any], log: Log) -> Tuple[List[str], List[str], str, str]:
    pros = normalize_string_list(source.get("quick_pros"), max_items=5, min_chars=6, strip_quotes=True)
    cons = normalize_string_list(source.get("quick_cons"), max_items=5, min_chars=6, strip_quotes=True)

    verdict_conf = normalize_confidence(source.get("verdict_confidence_suggested"))

    monetization_type = normalize_string(source.get("monetization_type"))
    official_url = normalize_string(source.get("official_url"))
    affiliate_link = resolve_affiliate_link(source, monetization_type, official_url, log)

    if monetization_type == "affiliate" and not affiliate_link:
        log.warn("W003 monetization_type is affiliate but no valid affiliate_link was provided.")

    if len(pros) == 0 or len(cons) == 0:
        if pros or cons or verdict_conf or affiliate_link:
            log.warn(
                "W005 Quick Verdict suppressed: both quick_pros and quick_cons must be non-empty to avoid empty shells in verdict-box.html."
            )
        return [], [], "", ""

    return pros, cons, verdict_conf, affiliate_link


def build_signal_sources(source: Dict[str, Any], log: Log) -> List[str]:
    raw = source.get("signal_sources")
    if raw is None:
        return []

    if isinstance(raw, dict):
        raw = raw.get("categories")

    if raw is None:
        return []
    if not isinstance(raw, list):
        log.error("E120 signal_sources must be a list of strings (or an object with categories: [...]).")
        return []

    return normalize_string_list(raw, max_items=5, min_chars=3, strip_quotes=True)


def normalize_quote(q: Any) -> Optional[Dict[str, str]]:
    if not isinstance(q, dict):
        return None
    text = strip_wrapping_quotes(normalize_string(q.get("text")))
    source_name = normalize_string(q.get("source"))
    link = normalize_string(q.get("link"))

    if not text or not source_name or not link:
        return None
    if not is_http_url(link):
        return None

    return {"text": text, "source": source_name, "link": link}


def build_recurring_signals(source: Dict[str, Any], log: Log) -> List[Dict[str, Any]]:
    raw = source.get("recurring_signals")
    if raw is None:
        return []
    if not isinstance(raw, list):
        log.error("E130 recurring_signals must be a list of objects.")
        return []

    kept: List[Dict[str, Any]] = []
    dropped = 0

    for item in raw:
        if not isinstance(item, dict):
            dropped += 1
            continue

        theme = normalize_string(item.get("theme"))
        descriptor = normalize_string(item.get("descriptor"))
        disagreement = normalize_string(item.get("disagreement"))
        fit_implication = normalize_string(item.get("fit_implication"))

        praise_quotes: List[Dict[str, str]] = []
        critique_quotes: List[Dict[str, str]] = []

        if isinstance(item.get("praise_quotes"), list):
            for q in item["praise_quotes"]:
                qq = normalize_quote(q)
                if qq:
                    praise_quotes.append(qq)
                    if len(praise_quotes) >= 3:
                        break

        if isinstance(item.get("critique_quotes"), list):
            for q in item["critique_quotes"]:
                qq = normalize_quote(q)
                if qq:
                    critique_quotes.append(qq)
                    if len(critique_quotes) >= 3:
                        break

        if (
            not theme
            or not descriptor
            or not disagreement
            or not fit_implication
            or len(praise_quotes) == 0
            or len(critique_quotes) == 0
        ):
            dropped += 1
            continue

        kept.append(
            {
                "theme": theme,
                "descriptor": descriptor,
                "praise_quotes": praise_quotes,
                "critique_quotes": critique_quotes,
                "disagreement": disagreement,
                "fit_implication": fit_implication,
            }
        )

        if len(kept) >= 4:
            break

    if dropped:
        log.warn(f"W007 recurring_signals dropped {dropped} incomplete item(s) to avoid empty shells.")

    if raw and not kept:
        log.warn("W007 recurring_signals provided but all items were dropped; section will be hidden.")

    return kept


def build_typical_alternatives(source: Dict[str, Any], tool_name: str, log: Log) -> List[Dict[str, str]]:
    raw = source.get("typical_alternatives")
    if raw is None:
        return []
    if not isinstance(raw, list):
        log.error("E140 typical_alternatives must be a list of objects.")
        return []

    dropped = 0
    out: List[Dict[str, str]] = []
    seen = set()

    for item in raw:
        if not isinstance(item, dict):
            dropped += 1
            continue

        name = normalize_string(item.get("name"))
        difference = normalize_string(item.get("difference"))
        best_for = normalize_string(item.get("best_for"))

        if not name or not difference or not best_for:
            dropped += 1
            continue

        if name.lower() == tool_name.lower():
            dropped += 1
            continue

        if name.lower() in seen:
            dropped += 1
            continue
        seen.add(name.lower())

        out.append({"name": name, "difference": difference, "best_for": best_for})
        if len(out) >= 4:
            break

    if dropped:
        log.warn(f"W009 typical_alternatives dropped {dropped} incomplete/duplicate item(s).")

    if out and "jasper" not in tool_name.lower():
        log.warn(
            "W010 Typical Alternatives suppressed (template debt): typical-alternatives.html intro is hardcoded to Jasper."
        )
        return []

    return out


def build_workflow_insights(source: Dict[str, Any], log: Log) -> Dict[str, Any]:
    raw = source.get("workflow_insights")
    if raw is None:
        return {"narrative": "", "tradeoffs": []}
    if not isinstance(raw, dict):
        log.error("E150 workflow_insights must be an object with narrative and tradeoffs.")
        return {"narrative": "", "tradeoffs": []}

    narrative = normalize_string(raw.get("narrative"))
    tradeoffs = normalize_string_list(raw.get("tradeoffs"), max_items=4, min_chars=10, strip_quotes=True)

    if not narrative or not tradeoffs:
        if narrative or tradeoffs:
            log.warn(
                "W011 Inside the Workflow suppressed: both workflow_insights.narrative and workflow_insights.tradeoffs are required to avoid empty shells in inside-workflow.html."
            )
        return {"narrative": "", "tradeoffs": []}

    return {"narrative": narrative, "tradeoffs": tradeoffs}


def build_illustrative_output(source: Dict[str, Any], log: Log) -> Dict[str, str]:
    raw = source.get("illustrative_output")
    if raw is None:
        return {"prompt": "", "sample_output": "", "interpretation": ""}

    if not isinstance(raw, dict):
        log.error("E160 illustrative_output must be an object with prompt, sample_output, and interpretation.")
        return {"prompt": "", "sample_output": "", "interpretation": ""}

    prompt = normalize_string(raw.get("prompt"))
    sample = strip_wrapping_quotes(normalize_string(raw.get("sample_output")))
    interpretation = normalize_string(raw.get("interpretation"))

    if interpretation and _TESTY_PHRASES_RE.search(interpretation):
        log.warn("W013 Illustrative Output contains benchmark/testing language; review trust framing.")

    if not prompt or not sample or not interpretation:
        if prompt or sample or interpretation:
            log.warn("W012 Illustrative Output suppressed: prompt, sample_output, and interpretation are all required.")
        return {"prompt": "", "sample_output": "", "interpretation": ""}

    return {"prompt": prompt, "sample_output": sample, "interpretation": interpretation}


# -------------------------
# Validation
# -------------------------

def require_str(source: Dict[str, Any], key: str, log: Log) -> str:
    if key not in source:
        log.error(f"E001 Missing required field: {key}")
        return ""
    if not isinstance(source[key], str):
        log.error(f"E002 Field '{key}' must be a string.")
        return ""
    return source[key]


def validate_container_types(source: Dict[str, Any], log: Log) -> None:
    if "pricing_notes" in source and source["pricing_notes"] is not None and not isinstance(source["pricing_notes"], list):
        log.error("E210 pricing_notes must be a list when provided.")
    if "quick_pros" in source and source["quick_pros"] is not None and not isinstance(source["quick_pros"], list):
        log.error("E211 quick_pros must be a list of strings when provided.")
    if "quick_cons" in source and source["quick_cons"] is not None and not isinstance(source["quick_cons"], list):
        log.error("E212 quick_cons must be a list of strings when provided.")

    if "signal_sources" in source and source["signal_sources"] is not None and not isinstance(source["signal_sources"], (list, dict)):
        log.error("E213 signal_sources must be a list of strings or an object with categories: [...].")

    if "recurring_signals" in source and source["recurring_signals"] is not None and not isinstance(source["recurring_signals"], list):
        log.error("E214 recurring_signals must be a list of objects when provided.")
    if "best_fit" in source and source["best_fit"] is not None and not isinstance(source["best_fit"], list):
        log.error("E215 best_fit must be a list of strings when provided.")
    if "not_ideal_for" in source and source["not_ideal_for"] is not None and not isinstance(source["not_ideal_for"], list):
        log.error("E216 not_ideal_for must be a list of strings when provided.")
    if "typical_alternatives" in source and source["typical_alternatives"] is not None and not isinstance(source["typical_alternatives"], list):
        log.error("E217 typical_alternatives must be a list of objects when provided.")
    if "workflow_insights" in source and source["workflow_insights"] is not None and not isinstance(source["workflow_insights"], dict):
        log.error("E218 workflow_insights must be an object when provided.")
    if "illustrative_output" in source and source["illustrative_output"] is not None and not isinstance(source["illustrative_output"], dict):
        log.error("E219 illustrative_output must be an object when provided.")
    if "overview" in source and source["overview"] is not None and not isinstance(source["overview"], (str, list)):
        log.error("E220 overview must be a string or a list of paragraph strings when provided.")


# -------------------------
# Load / Write
# -------------------------

def load_source(path: Path, log: Log) -> Optional[Dict[str, Any]]:
    if not path.exists():
        log.error(f"E100 Input file not found: {path}")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error(f"E101 Invalid JSON: {e}")
        return None

    if not isinstance(data, dict):
        log.error("E102 source_input.json top-level must be a JSON object.")
        return None

    return data


def write_output(path: Path, draft: Dict[str, Any], *, force: bool, log: Log) -> bool:
    if path.exists() and not force:
        log.error(f"E300 Output file already exists: {path} (use --force to overwrite)")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return True


# -------------------------
# Transform
# -------------------------

def transform(source: Dict[str, Any], log: Log) -> Tuple[Dict[str, Any], str]:
    tool_name = normalize_string(require_str(source, "tool_name", log))
    slug = normalize_string(require_str(source, "slug", log))
    tagline = normalize_string(require_str(source, "tagline", log))
    official_url = normalize_string(require_str(source, "official_url", log))
    monetization_type = normalize_string(require_str(source, "monetization_type", log))

    if not slug:
        log.error("E003 slug must not be blank.")
    elif not validate_slug(slug):
        log.error("E004 slug must contain only lowercase letters, numbers, and hyphens.")

    if not tool_name:
        log.error("E005 tool_name must not be blank.")

    if not is_http_url(official_url):
        log.error("E006 official_url must be a valid http(s) URL.")

    if monetization_type not in _ALLOWED_MONETIZATION:
        log.error(f"E007 monetization_type must be one of: {', '.join(sorted(_ALLOWED_MONETIZATION))}.")

    if not tagline:
        log.warn("W001 tagline is blank; the header will omit it.")

    validate_container_types(source, log)

    if log.has_errors():
        return {}, slug

    draft: Dict[str, Any] = {
        "layout": "tool",
        "tool_name": tool_name,
        "tagline": tagline,
        "logo_url": resolve_logo_url(source, log),
        "official_url": official_url,
        "monetization_type": monetization_type,
        "pricing_tiers": normalize_pricing_tiers(source.get("pricing_notes"), log),
        "last_updated": normalize_last_updated(source.get("last_updated"), log),
        "quick_pros": [],
        "quick_cons": [],
        "verdict_confidence": "",
        "affiliate_link": "",
        "signal_sources": {"categories": []},
        "recurring_signals": [],
        "best_fit": [],
        "not_ideal_for": [],
        "typical_alternatives": [],
        "workflow_insights": {"narrative": "", "tradeoffs": []},
        "illustrative_output": {"prompt": "", "sample_output": "", "interpretation": ""},
        "overview": "",
    }

    qp, qc, vc, al = build_quick_verdict(source, log)
    draft["quick_pros"] = qp
    draft["quick_cons"] = qc
    draft["verdict_confidence"] = vc
    draft["affiliate_link"] = al

    cats = build_signal_sources(source, log)
    if log.has_errors():
        return {}, slug
    draft["signal_sources"] = {"categories": cats}

    rs = build_recurring_signals(source, log)
    if log.has_errors():
        return {}, slug
    draft["recurring_signals"] = rs

    best_fit = normalize_string_list(source.get("best_fit"), max_items=3, min_chars=6, strip_quotes=True)
    not_ideal = normalize_string_list(source.get("not_ideal_for"), max_items=3, min_chars=6, strip_quotes=True)
    if (best_fit and not not_ideal) or (not_ideal and not best_fit):
        log.warn("W008 Best Fit / Not Ideal For incomplete: both lists required to render; section will be hidden.")
        best_fit, not_ideal = [], []
    draft["best_fit"] = best_fit
    draft["not_ideal_for"] = not_ideal

    ta = build_typical_alternatives(source, tool_name, log)
    if log.has_errors():
        return {}, slug
    draft["typical_alternatives"] = ta

    wi = build_workflow_insights(source, log)
    if log.has_errors():
        return {}, slug
    draft["workflow_insights"] = wi

    io = build_illustrative_output(source, log)
    if log.has_errors():
        return {}, slug
    draft["illustrative_output"] = io

    ov = normalize_overview(source.get("overview"), log)
    if not ov:
        log.warn("W014 Overview is missing or empty; published pages should include a real overview.")
    draft["overview"] = ov

    return draft, slug


# -------------------------
# Main
# -------------------------

def main() -> int:
    args = build_parser().parse_args()
    log = Log()

    source_path = Path(args.input)
    source = load_source(source_path, log)
    if source is None:
        return 1

    draft, slug = transform(source, log)
    if log.has_errors():
        return 1

    if args.output.strip():
        out_path = Path(args.output)
    else:
        repo_root = Path.cwd()
        out_path = repo_root / "automation" / "drafts" / f"{slug}.draft.json"

    if not write_output(out_path, draft, force=args.force, log=log):
        return 1

    if not args.quiet:
        print(f"Wrote draft.json: {out_path}")
        if log.warnings:
            print(f"Warnings: {len(log.warnings)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
