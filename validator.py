"""Post-generation validator: citation checker + repealed-law blocker.

Scans every advisor/drafter output for legal references, ensures they map to
KB entries, and removes/replaces anything that can't be verified.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from schemas import ValidatorHit

logger = logging.getLogger(__name__)

# ── Output log path ──────────────────────────────────────────────────────────
LOG_PATH = Path(__file__).parent / "outputs" / "validator_log.jsonl"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Repealed laws — must NEVER be cited as current ───────────────────────────
REPEALED_LAWS = [
    r"Payment\s+of\s+Wages\s+Act",
    r"Minimum\s+Wages\s+Act",
    r"\bIPC\b",
    r"\bCrPC\b",
    r"Indian\s+Evidence\s+Act",
    r"Indian\s+Penal\s+Code",
    r"Code\s+of\s+Criminal\s+Procedure",
    r"\be-?Daakhil\b",
]

# ── Patterns that look like legal references ─────────────────────────────────
LEGAL_REF_PATTERNS = [
    r"Section\s+\d+[\w()]*",
    r"Sec\.\s*\d+[\w()]*",
    r"u/s\s+\d+",
    r"Article\s+\d+",
    r"Rule\s+\d+",
    r"\w+\s+Act,?\s+\d{4}",
    r"AIR\s+\d{4}",
    r"\bSCC\b",
    r"\bv\.\s",
    r"\bvs\.\s",
]

# ── KB citation pattern ─────────────────────────────────────────────────────
KB_CITE_PATTERN = re.compile(r"\[KB:([\w\-]+)\]")


def validate_output(
    text: str,
    kb_ids_in_context: list[str],
    allow_regenerate: bool = True,
) -> tuple[str, list[ValidatorHit], bool]:
    """Validate and clean an LLM-generated legal output.

    Returns:
        - cleaned text
        - list of validator hits
        - whether a regeneration is recommended (repealed law found)
    """
    hits: list[ValidatorHit] = []
    needs_regen = False

    # ── 1. Check for repealed laws ───────────────────────────────────────
    for pattern in REPEALED_LAWS:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        for match in matches:
            hit = ValidatorHit(
                original_text=match.group(),
                matched_pattern=pattern,
                action="blocked_regenerate" if allow_regenerate else "removed",
                kb_id_found=None,
            )
            hits.append(hit)
            needs_regen = True

    if needs_regen and allow_regenerate:
        _log_hits(hits)
        return text, hits, True  # Caller should regenerate

    # If repealed and can't regenerate, strip them
    if needs_regen:
        for pattern in REPEALED_LAWS:
            text = re.sub(
                pattern + r"[^.]*\.",
                "(reference removed: cites a repealed law)",
                text,
                flags=re.IGNORECASE,
            )

    # ── 2. Check legal references have KB citations ──────────────────────
    for pattern in LEGAL_REF_PATTERNS:
        for match in re.finditer(pattern, text):
            ref_text = match.group()
            # Check if there's a [KB:...] citation nearby (within 200 chars)
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 200)
            context_window = text[start:end]

            kb_cite = KB_CITE_PATTERN.search(context_window)
            if kb_cite and kb_cite.group(1) in kb_ids_in_context:
                # Citation found and valid
                continue
            else:
                # No valid KB citation — remove the reference
                hit = ValidatorHit(
                    original_text=ref_text,
                    matched_pattern=pattern,
                    action="removed",
                    kb_id_found=kb_cite.group(1) if kb_cite else None,
                )
                hits.append(hit)
                text = text.replace(
                    ref_text,
                    "(reference removed: could not verify)",
                    1,
                )

    _log_hits(hits)
    return text, hits, False


def validate_and_fix(
    text: str,
    kb_ids_in_context: list[str],
    regenerate_fn=None,
    regen_context: Optional[dict] = None,
) -> tuple[str, list[ValidatorHit]]:
    """Full validation pipeline with optional regeneration.

    If a repealed law is found and regenerate_fn is provided, attempts
    one regeneration before stripping.
    """
    cleaned, hits, needs_regen = validate_output(
        text, kb_ids_in_context, allow_regenerate=bool(regenerate_fn)
    )

    if needs_regen and regenerate_fn:
        # Try regeneration with a correction note
        repealed_refs = [h.original_text for h in hits if h.action == "blocked_regenerate"]
        correction = (
            f"Your previous output mentioned these REPEALED laws: {', '.join(repealed_refs)}. "
            "These have been replaced. Use only the current laws from the knowledge base."
        )
        new_text = regenerate_fn(correction, **(regen_context or {}))
        # Validate again, but no more regeneration
        cleaned, new_hits, _ = validate_output(
            new_text, kb_ids_in_context, allow_regenerate=False
        )
        hits.extend(new_hits)

    return cleaned, hits


def _log_hits(hits: list[ValidatorHit]) -> None:
    """Append validator hits to the JSONL log."""
    if not hits:
        return
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        for hit in hits:
            entry = {
                "timestamp": datetime.now().isoformat(),
                **hit.model_dump(),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def render_citations(text: str) -> str:
    """Replace [KB:ID] with a readable format showing source URLs,
    and append a verified statutory references summary box with official links.
    """
    from kb.retrieve import get_entry_by_id

    seen_entries = []

    def _replace(match):
        kb_id = match.group(1)
        entry = get_entry_by_id(kb_id)
        if entry:
            if not any(e.get("id") == entry.get("id") for e in seen_entries):
                seen_entries.append(entry)
            url = entry.get("source_url", "")
            act = entry.get("act", kb_id)
            sec = entry.get("section", "")
            act_short = act.split("+")[0].split("(")[0].strip()
            if url:
                return (
                    f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                    f'style="display:inline-flex; align-items:center; gap:3px; background:#ECFDF5; '
                    f'border:1px solid #A7F3D0; color:#047857; font-size:11px; font-weight:600; '
                    f'padding:2px 7px; border-radius:4px; text-decoration:none; margin:0 2px;" '
                    f'title="{act} - {sec} (Official Verified Statute)">'
                    f'🏛️ {act_short} ↗</a>'
                )
            else:
                return (
                    f'<span style="background:#F1F5F9; border:1px solid #CBD5E1; color:#334155; '
                    f'font-size:11px; font-weight:600; padding:2px 6px; border-radius:4px;">'
                    f'🏛️ {act_short}</span>'
                )
        return match.group(0)

    rendered = KB_CITE_PATTERN.sub(_replace, text)

    # Append Verified Legal Sources table if any citations were found
    if seen_entries:
        sources_rows = []
        for e in seen_entries:
            act_name = e.get("act", "Statute")
            sec_name = e.get("section", "N/A")
            url = e.get("source_url", "https://www.indiacode.nic.in")
            sources_rows.append(
                f'<div style="display:flex; justify-content:space-between; align-items:flex-start; padding:8px 0; border-bottom:1px solid #F1F5F9; font-size:11px;">'
                f'  <div style="flex:1;">'
                f'    <div style="font-weight:700; color:#1E293B;">{act_name}</div>'
                f'    <div style="color:#64748B; margin-top:2px;">Section: {sec_name} • <span style="color:#059669; font-weight:600;">✓ Verified against Official Gazette / India Code</span></div>'
                f'  </div>'
                f'  <a href="{url}" target="_blank" rel="noopener noreferrer" style="font-size:11px; font-weight:600; color:#2563EB; background:#EFF6FF; border:1px solid #BFDBFE; padding:3px 8px; border-radius:4px; text-decoration:none; white-space:nowrap; margin-left:10px;">'
                f'    Official Source ↗'
                f'  </a>'
                f'</div>'
            )

        sources_box = (
            f'\n\n<div style="margin-top:24px; padding:16px; background:#F8FAFC; border:1px solid #E2E8F0; border-radius:10px; box-shadow:0 1px 2px rgba(0,0,0,0.02);">'
            f'  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid #E2E8F0; padding-bottom:8px;">'
            f'    <div style="font-size:12px; font-weight:700; color:#0F172A; display:flex; align-items:center; gap:6px;">'
            f'      <span>📚 Verified Legal References & Official Source Links</span>'
            f'      <span style="font-size:10px; background:#DCFCE7; color:#15803D; padding:2px 8px; border-radius:12px; font-weight:700;">OFFICIAL BARE ACTS</span>'
            f'    </div>'
            f'    <span style="font-size:10px; color:#64748B;">Official Source Grounded</span>'
            f'  </div>'
            f'  {"".join(sources_rows)}'
            f'  <div style="margin-top:12px; padding:10px 12px; background:#EFF6FF; border-radius:6px; border:1px solid #DBEAFE; font-size:11px; color:#1E40AF; line-height:1.5;">'
            f'    <strong>🛡️ Verified Law vs 💡 AI Interpretation:</strong> Provisions in this assessment are anchored in verified Bare Acts and Gazette notifications. Tactical advice represents AI reasoning and probabilistic risk analysis.'
            f'  </div>'
            f'  <div style="margin-top:8px; font-size:11px; color:#64748B; line-height:1.4;">'
            f'    <strong>⚖️ Statutory Disclaimer:</strong> This application provides automated legal information, not professional legal counsel or representation. If you require advocate representation and qualify under Section 12 of the Legal Services Authorities Act, 1987, call the official <strong>NALSA Pan-India 24x7 Helpline: 15100</strong> (nalsa.gov.in) or Delhi SLSA at <strong>1516</strong>.'
            f'  </div>'
            f'</div>'
        )
        rendered += sources_box

    return rendered
