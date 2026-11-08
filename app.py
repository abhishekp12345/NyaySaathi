"""NyaySaathi (न्याय साथी) — AI Legal Assistant for Everyday Money Recovery in India.

Conversational legal assistant for pre-litigation money recovery under ₹50 Lakh:
- Residential Tenancy Deposits (Transfer of Property Act, 1882)
- Consumer Refunds / Defective Goods / Deficient Services (Consumer Protection Act, 2019)
- Unpaid Salaries & Final Settlements (Code on Wages, 2019)

Core Workflow:
1. Multilingual Natural Language & Voice Intake (Hindi, English, Hinglish, Regional)
2. Deterministic Rules Engine (Escalation, Statutory Limitation, Forum Selection, Missing Proof)
3. Verified Bare Acts Grounding (India Code official citations, zero hallucinated case law)
4. Formal Legal Notice Generator with customizable cure period (.docx download)
5. Practice Dialogue Mode (Counterparty negotiation simulation with strategic tips)
"""

from __future__ import annotations

import sys
import json
import logging

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import os
import re
import html
import tempfile
from datetime import datetime, date, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

# Automatically load environment variables from .env file if present
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

import docx
import gradio as gr
from pydantic import ValidationError

from schemas import (
    CaseFile,
    CaseCategory,
    IntakeResponse,
    RulesResult,
    DocType,
)
from llm import chat, chat_json, get_model
from rules import run_rules, _check_missing_proof
from kb.retrieve import get_entries_for_case, get_all_entries, get_entry_by_id
from validator import validate_and_fix, render_citations
from stt import transcribe
from action_plan import (
    generate_action_plan,
    render_action_plan_dashboard,
    generate_action_plan_docx,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── State Machine ────────────────────────────────────────────────────────────

class Stage(str, Enum):
    WELCOME = "welcome"
    INTAKE = "intake"
    CONFIRM = "confirm"
    ADVICE = "advice"
    DRAFT = "draft"
    PRACTICE = "practice"
    ESCALATED = "escalated"


def load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")


def detect_language(text: str) -> str:
    resp = chat(
        [
            {"role": "system", "content": (
                "Detect the language and script of this text. Reply with ONLY the "
                "language name (e.g., 'English', 'Hindi', 'Hinglish', 'Tamil', "
                "'Bengali', 'Marathi', 'Telugu', 'Kannada'). Nothing else."
            )},
            {"role": "user", "content": text},
        ],
        temperature=0.0,
        max_tokens=20,
    )
    return resp.strip().strip('"').strip("'")


def run_intake(user_msg: str, casefile: CaseFile, language: str) -> IntakeResponse:
    if isinstance(casefile, dict):
        try:
            casefile = CaseFile.model_validate(casefile)
        except Exception:
            casefile = CaseFile()

    prompt = load_prompt("intake")
    prompt = prompt.replace("{user_language}", language)
    prompt = prompt.replace("{casefile_schema_json}", str(CaseFile.model_json_schema()))

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": (
            f"Current CaseFile state:\n{casefile.model_dump_json(indent=2)}\n\n"
            f"User says: {user_msg}"
        )},
    ]
    return chat_json(messages, IntakeResponse)


def run_advisor(casefile: CaseFile, rules_result: RulesResult, language: str) -> str:
    if isinstance(casefile, dict):
        try:
            casefile = CaseFile.model_validate(casefile)
        except Exception:
            casefile = CaseFile()
    if isinstance(rules_result, dict):
        try:
            rules_result = RulesResult.model_validate(rules_result)
        except Exception:
            rules_result = run_rules(casefile)
    elif not isinstance(rules_result, RulesResult):
        rules_result = run_rules(casefile)

    from kb.retrieve import search_legal_rag
    rag_provisions = search_legal_rag(casefile.story_summary or "", casefile, top_k=6)
    kb_ids = [r.id for r in rag_provisions]

    compact_kb = [
        {
            "id": r.id,
            "act": r.act_name,
            "section": r.section,
            "source_url": r.source_url,
            "summary": r.statutory_summary,
            "practical_guidance": r.practical_guidance,
            "official_citation": r.official_citation,
        }
        for r in rag_provisions
    ]

    prompt = load_prompt("advisor")
    prompt = prompt.replace("{user_language}", language)
    prompt = prompt.replace("{casefile_json}", casefile.model_dump_json(indent=2))
    prompt = prompt.replace("{rules_json}", rules_result.model_dump_json(indent=2))
    prompt = prompt.replace("{kb_entries_json}", json.dumps(compact_kb, indent=2, ensure_ascii=False))

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "Please analyze this dispute and provide: 1. Summary of the problem, 2. Relevant legal issues, 3. Potentially applicable Indian laws, 4. Rights and possible remedies, and 5. Recommended next steps."}
    ]
    raw_advice = chat(messages, temperature=0.3, max_tokens=2500)

    def _regen(correction, **kw):
        msgs = messages + [
            {"role": "assistant", "content": raw_advice},
            {"role": "user", "content": correction},
        ]
        return chat(msgs, temperature=0.2, max_tokens=2500)

    cleaned, hits = validate_and_fix(raw_advice, kb_ids, regenerate_fn=_regen)
    return cleaned


def run_drafter(casefile: CaseFile, rules_result: RulesResult, language: str) -> str:
    if isinstance(casefile, dict):
        try:
            casefile = CaseFile.model_validate(casefile)
        except Exception:
            casefile = CaseFile()
    if isinstance(rules_result, dict):
        try:
            rules_result = RulesResult.model_validate(rules_result)
        except Exception:
            rules_result = run_rules(casefile)
    elif not isinstance(rules_result, RulesResult):
        rules_result = run_rules(casefile)

    kb_entries = get_entries_for_case(casefile)
    kb_ids = [e["id"] for e in kb_entries]
    doc_type = rules_result.doc_type.value if rules_result and rules_result.doc_type else "legal_notice"

    prompt = load_prompt("drafter")
    prompt = prompt.replace("{doc_type}", doc_type)
    prompt = prompt.replace("{user_language}", language)
    prompt = prompt.replace("{casefile_json}", casefile.model_dump_json(indent=2))
    prompt = prompt.replace("{rules_json}", rules_result.model_dump_json(indent=2))

    compact_kb = [
        {
            "id": e["id"],
            "act": e.get("act"),
            "section": e.get("section"),
            "summary": e.get("plain_summary", "").strip()
        }
        for e in kb_entries
    ]
    prompt = prompt.replace("{kb_entries_json}", json.dumps(compact_kb, indent=2, ensure_ascii=False))

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Please generate the formal {doc_type} using the confirmed facts and knowledge base."}
    ]
    raw_draft = chat(messages, temperature=0.2, max_tokens=2000)

    def _regen(correction, **kw):
        msgs = messages + [
            {"role": "assistant", "content": raw_draft},
            {"role": "user", "content": correction},
        ]
        return chat(msgs, temperature=0.1, max_tokens=2000)

    cleaned, hits = validate_and_fix(raw_draft, kb_ids, regenerate_fn=_regen)
    return cleaned


def generate_docx(draft_text: str, casefile: CaseFile) -> str:
    if isinstance(casefile, dict):
        try:
            casefile = CaseFile.model_validate(casefile)
        except Exception:
            casefile = CaseFile()

    doc = docx.Document()
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Arial"
    font.size = docx.shared.Pt(11)

    title_map = {
        CaseCategory.DEPOSIT: "LEGAL NOTICE — Demand for Return of Security Deposit",
        CaseCategory.CONSUMER: "CONSUMER COMPLAINT",
        CaseCategory.SALARY: "DEMAND LETTER — Unpaid Salary / Final Settlement",
    }
    title = title_map.get(casefile.category, "LEGAL NOTICE") if casefile else "LEGAL NOTICE"
    heading = doc.add_heading(title, level=1)
    heading.alignment = docx.enum.text.WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph(f"Date: {datetime.now().strftime('%d %B %Y')}")
    doc.add_paragraph("")

    for paragraph in draft_text.split("\n"):
        paragraph = paragraph.strip()
        if paragraph:
            doc.add_paragraph(paragraph)

    doc.add_paragraph("")
    doc.add_paragraph("")
    doc.add_paragraph("-" * 50)
    disclaimer = doc.add_paragraph()
    disclaimer.alignment = docx.enum.text.WD_ALIGN_PARAGRAPH.CENTER
    run = disclaimer.add_run(
        "STATUTORY NOTICE & DISCLAIMER: This document draft was prepared using NyaySaathi (न्याय साथी) AI Legal Assistant based on codified Indian law. "
        "It provides automated legal information and does NOT constitute professional legal advice or create an advocate-client relationship under the Advocates Act, 1961. "
        "Review with an advocate enrolled with the Bar Council of India before formal dispatch. "
        "For free official legal aid, contact the National Legal Services Authority (NALSA) 24x7 Pan-India Helpline: 15100 (or Delhi SLSA: 1516)."
    )
    run.italic = True
    run.font.size = docx.shared.Pt(8.5)

    out_dir = Path(__file__).parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    filename = f"legal_notice_{casefile.category.value if casefile and casefile.category else 'dispute'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    filepath = out_dir / filename
    doc.save(str(filepath))
    return str(filepath)


def escalation_message(reason: str, language: str) -> str:
    msg = chat(
        [
            {"role": "system", "content": (
                f"Reply in {language}. You are an AI legal intake specialist. The user's matter requires professional assistance or escalation. "
                "Explain clearly, respectfully, and without legal jargon why this matter cannot be handled via automated civil notices. "
                "Provide verified NALSA Pan-India 24x7 Helpline: 15100 (and Delhi SLSA 1516 under Section 12 of Legal Services Authorities Act, 1987), National Consumer Helpline 1915, and emergency police 112."
            )},
            {"role": "user", "content": f"The case cannot be handled because: {reason}. Please provide the routing guidance."}
        ],
        temperature=0.2,
        max_tokens=400,
    )
    return msg


def format_casefile_card(cf: CaseFile) -> str:
    if isinstance(cf, dict):
        try:
            cf = CaseFile.model_validate(cf)
        except Exception:
            pass
    lines = ["**Dispute Summary**\n"]
    category_labels = {
        CaseCategory.DEPOSIT: "Security Deposit (Tenancy)",
        CaseCategory.CONSUMER: "Consumer Dispute",
        CaseCategory.SALARY: "Unpaid Salary / Settlement",
    }
    cat = category_labels.get(cf.category, "Civil Dispute") if cf.category else "Under Review"
    lines.append(f"• **Category:** {cat}")
    if cf.amount_claimed:
        lines.append(f"• **Amount Claimed:** ₹{cf.amount_claimed:,.0f} {cf.currency}")
    if cf.opponent_name:
        lines.append(f"• **Opponent:** {cf.opponent_name} ({cf.opponent_type or 'Opponent'})")
    loc = [cf.city, cf.state]
    loc_str = ", ".join(p for p in loc if p)
    if loc_str:
        lines.append(f"• **Location:** {loc_str}")
    if cf.proof_available:
        lines.append(f"• **Evidence Available:** {', '.join(cf.proof_available)}")
    if cf.story_summary:
        lines.append(f"\n{cf.story_summary}")
    return "\n".join(lines)


# ── UI HTML Renderers ────────────────────────────────────────────────────────

def render_case_analysis_cards(
    summary_items: list[str],
    risk_items: list[str],
    next_step_items: list[str],
    casefile: Optional[CaseFile] = None
) -> str:
    def make_list(items):
        if not items:
            return "<p style='color:#6B7280; font-size:12px; margin:0;'>Awaiting dispute details...</p>"
        lis = "".join(f"<li style='margin-bottom:6px;'>{it}</li>" for it in items)
        return f"<ul style='margin:0; padding-left:16px; font-size:12px; line-height:1.5;'>{lis}</ul>"

    cards = f"""
    <div style="display:flex; gap:12px; width:100%;">
      <div style="flex:1; background:#EEF2FF; border:1px solid #C7D2FE; border-radius:10px; padding:14px; box-shadow:0 1px 3px rgba(0,0,0,0.03);">
        <div style="font-weight:700; color:#1E1B4B; font-size:13px; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
          <span>Key Issues</span>
          <span style="font-size:9px; background:#E0E7FF; color:#3730A3; padding:1px 5px; border-radius:6px; font-weight:700;">FACTS</span>
        </div>
        <div style="color:#312E81;">
          {make_list(summary_items)}
        </div>
      </div>
      <div style="flex:1; background:#FFF1F2; border:1px solid #FECDD3; border-radius:10px; padding:14px; box-shadow:0 1px 3px rgba(0,0,0,0.03);">
        <div style="font-weight:700; color:#9F1239; font-size:13px; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
          <span>Risks</span>
          <span style="font-size:9px; background:#FFE4E6; color:#9F1239; padding:1px 5px; border-radius:6px; font-weight:700;">LEGAL</span>
        </div>
        <div style="color:#881337;">
          {make_list(risk_items)}
        </div>
      </div>
      <div style="flex:1; background:#F0FDF4; border:1px solid #BBF7D0; border-radius:10px; padding:14px; box-shadow:0 1px 3px rgba(0,0,0,0.03);">
        <div style="font-weight:700; color:#065F46; font-size:13px; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
          <span>Next Steps</span>
          <span style="font-size:9px; background:#DCFCE7; color:#15803D; padding:1px 5px; border-radius:6px; font-weight:700;">STRATEGY</span>
        </div>
        <div style="color:#047857;">
          {make_list(next_step_items)}
        </div>
      </div>
    </div>
    """
    return cards


def render_document_preview(draft_text: str, filename: str = "Legal_Notice_Draft.docx") -> str:
    if not draft_text:
        return f"""
        <div style="border:1px dashed #D1D5DB; border-radius:8px; padding:32px 20px; text-align:center; background:#FFFFFF; color:#6B7280;">
          <div style="font-size:24px; margin-bottom:8px;">📄</div>
          <div style="font-size:14px; font-weight:600; color:#374151;">No Document Generated Yet</div>
          <div style="font-size:12px; margin-top:4px;">Submit your dispute or click <strong>📝 Generate Legal Notice</strong> to draft a formal Legal Notice / Demand Letter.</div>
        </div>
        """

    formatted = draft_text.replace("<", "&lt;").replace(">", "&gt;")
    formatted = re.sub(
        r"(\[KB:[\w\-]+\])",
        r"<span style='background:#FEF08A; color:#854D0E; font-weight:600; padding:1px 4px; border-radius:3px;'>\1</span>",
        formatted
    )
    formatted_paragraphs = "".join(f"<p style='margin-bottom:10px;'>{p}</p>" for p in formatted.split("\n") if p.strip())

    return f"""
    <div style="background:#FFFFFF; border:1px solid #E5E7EB; border-radius:8px; padding:20px; font-family:'Georgia', serif; font-size:12px; line-height:1.6; color:#1F2937; max-height:360px; overflow-y:auto; box-shadow:inset 0 1px 2px rgba(0,0,0,0.03);">
      <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #E5E7EB; padding-bottom:10px; margin-bottom:14px;">
        <span style="font-family:sans-serif; font-size:11px; font-weight:700; color:#4F46E5; text-transform:uppercase; letter-spacing:0.05em;">{filename}</span>
        <span style="font-family:sans-serif; font-size:11px; background:#FEF3C7; color:#92400E; padding:2px 8px; border-radius:12px; font-weight:600;">Statutory Pre-Litigation Notice</span>
      </div>
      <div style="text-align:center; font-weight:bold; font-size:14px; text-decoration:underline; margin-bottom:16px;">
        FORMAL LEGAL NOTICE / DEMAND LETTER
      </div>
      <div>
        {formatted_paragraphs}
      </div>
    </div>
    """


def parse_advice_sections(advice_text: str) -> tuple[list[str], list[str], list[str]]:
    summary_items = []
    risk_items = []
    next_step_items = []

    p_summary = re.search(r"### 1\. Summary of the Problem\s*\n(.*?)(?=###|\Z)", advice_text, re.DOTALL | re.IGNORECASE)
    p_issues = re.search(r"### 2\. Relevant Legal Issues\s*\n(.*?)(?=###|\Z)", advice_text, re.DOTALL | re.IGNORECASE)
    p_laws = re.search(r"### 3\. Potentially Applicable Indian Laws\s*\n(.*?)(?=###|\Z)", advice_text, re.DOTALL | re.IGNORECASE)
    p_remedies = re.search(r"### 4\. Rights and Possible Remedies\s*\n(.*?)(?=###|\Z)", advice_text, re.DOTALL | re.IGNORECASE)
    p_next = re.search(r"### 5\. Recommended Next Steps\s*\n(.*?)(?=###|\Z)", advice_text, re.DOTALL | re.IGNORECASE)

    def extract_bullets(text: Optional[re.Match], fallback_max: int = 3) -> list[str]:
        if not text:
            return []
        lines = [line.strip().lstrip("-•* \t") for line in text.group(1).split("\n") if line.strip()]
        clean = [l for l in lines if not l.startswith("#") and len(l) > 10]
        return clean[:fallback_max]

    s_bullets = extract_bullets(p_summary, 2)
    i_bullets = extract_bullets(p_issues, 2)
    l_bullets = extract_bullets(p_laws, 3)
    r_bullets = extract_bullets(p_remedies, 2)
    n_bullets = extract_bullets(p_next, 2)

    summary_items = s_bullets + i_bullets if (s_bullets or i_bullets) else ["Dispute details under review", "Parties and claim identified"]
    risk_items = l_bullets if l_bullets else ["Statutory protections evaluated", "Limitation period active"]
    next_step_items = r_bullets + n_bullets if (r_bullets or n_bullets) else ["Send formal legal notice", "Preserve transaction proofs"]

    return summary_items[:3], risk_items[:3], next_step_items[:3]


# ── CSS Styling ──────────────────────────────────────────────────────────────

DASHBOARD_CSS = """
:root {
    --bg-page: #F8FAFC;
    --border-color: #E2E8F0;
    --text-main: #0F172A;
    --primary: #4F46E5;
}

body, html, .gradio-container {
    background-color: var(--bg-page) !important;
    color: var(--text-main) !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
    margin: 0 !important;
    padding: 0 !important;
    max-width: 100% !important;
}

.gradio-container {
    padding: 16px 24px !important;
}

.app-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 20px;
    background: #FFFFFF;
    border: 1px solid var(--border-color);
    border-radius: 12px;
    margin-bottom: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.brand-title {
    font-size: 18px;
    font-weight: 700;
    color: #1E1B4B;
    display: flex;
    align-items: center;
    gap: 8px;
}

.brand-badge {
    font-size: 11px;
    background: #EEF2FF;
    color: #4F46E5;
    padding: 2px 8px;
    border-radius: 12px;
    font-weight: 600;
}

.header-status {
    font-size: 11px;
    color: #15803D;
    background: #DCFCE7;
    padding: 4px 10px;
    border-radius: 20px;
    font-weight: 600;
}

.voice-input-card {
    background: #F8FAFC;
    border: 1px dashed #CBD5E1;
    border-radius: 8px;
    padding: 10px 14px;
    margin-top: 10px;
}

.chatbot-wrapper .message.user {
    background-color: #0D5C58 !important;
    color: #FFFFFF !important;
    border-radius: 14px 14px 2px 14px !important;
}

.chatbot-wrapper .message.bot {
    background-color: #F3F4F6 !important;
    color: #1F2937 !important;
    border-radius: 14px 14px 14px 2px !important;
}

.panel-card {
    background: #FFFFFF;
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    margin-bottom: 12px;
}

.panel-header-title {
    font-size: 15px;
    font-weight: 700;
    color: #111827;
    margin: 0;
}

.panel-header-sub {
    font-size: 12px;
    color: #6B7280;
    margin: 2px 0 12px 0;
}
"""


# ── Gradio Application ───────────────────────────────────────────────────────

def create_app():
    with gr.Blocks(title="NyaySaathi (न्याय साथी) — AI Legal Assistant") as app:

        state_stage = gr.State(Stage.WELCOME)
        state_casefile = gr.State(CaseFile())
        state_rules = gr.State(None)
        state_language = gr.State("English")
        state_draft_text = gr.State("")
        state_practice_history = gr.State([])
        state_practice_turns = gr.State(0)

        # Top Bar (Clean, Unified Header)
        gr.HTML("""
        <div class="app-header">
          <div style="display:flex; align-items:center; gap:12px;">
            <div style="width:32px; height:32px; background:#1E1B4B; border-radius:8px; display:flex; align-items:center; justify-content:center; color:#FFFFFF; font-weight:bold; font-size:16px;">
              ⚖️
            </div>
            <div>
              <div class="brand-title">
                NyaySaathi (न्याय साथी) <span class="brand-badge">AI Legal Assistant</span>
              </div>
              <div style="font-size:11px; color:#6B7280;">
                Everyday Money Recovery in India • Residential Tenancy Deposits, Consumer Refunds, Unpaid Salaries
              </div>
            </div>
          </div>
          <div style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:11px; background:#EEF2FF; color:#4F46E5; border:1px solid #C7D2FE; padding:3px 10px; border-radius:20px; font-weight:600;">🛡️ Verified Bare Acts</span>
            <span style="font-size:11px; background:#FEF3C7; color:#92400E; border:1px solid #FDE68A; padding:3px 10px; border-radius:20px; font-weight:600;">⚖️ Info Only • NALSA 15100</span>
            <div class="header-status">● SYSTEM ACTIVE (GROQ QWEN)</div>
          </div>
        </div>
        """)

        gr.HTML("""
        <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:10px 16px; margin-bottom:12px; font-size:11px; color:#475569; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <span style="font-weight:700; color:#1E1B4B; display:flex; align-items:center; gap:4px;">
              <span>🛡️ Trust & Reliability Framework:</span>
            </span>
            <span style="background:#EFF6FF; color:#1E40AF; padding:2px 8px; border-radius:10px; font-weight:600;">1. Verified Bare Acts & Source Links</span>
            <span style="background:#F0FDF4; color:#166534; padding:2px 8px; border-radius:10px; font-weight:600;">2. Law vs. AI Interpretation Distinct</span>
            <span style="background:#FEF3C7; color:#92400E; padding:2px 8px; border-radius:10px; font-weight:600;">3. Data Sufficiency Warnings</span>
            <span style="background:#F1F5F9; color:#334155; padding:2px 8px; border-radius:10px; font-weight:600;">4. Local In-Memory Privacy</span>
          </div>
          <div style="display:flex; align-items:center; gap:6px;">
            <span style="color:#64748B;">Official Pan-India Legal Aid:</span>
            <a href="https://nalsa.gov.in" target="_blank" style="color:#7C3AED; font-weight:700; text-decoration:none; background:#FAF5FF; border:1px solid #E9D5FF; padding:2px 8px; border-radius:10px;">NALSA 15100 (Toll-Free) ↗</a>
          </div>
        </div>
        """)

        with gr.Row():
            # Column 1: Chat & Voice Consultation (50%)
            with gr.Column(scale=6):
                with gr.Group(elem_classes="panel-card"):
                    gr.HTML("""
                    <div style="margin-bottom:12px;">
                      <h3 class="panel-header-title">Chat & Voice Consultation</h3>
                      <p class="panel-header-sub">Describe your dispute in English, Hindi, Hinglish, or regional languages.</p>
                    </div>
                    """)

                    chatbot = gr.Chatbot(
                        value=[
                            {
                                "role": "assistant",
                                "content": (
                                    "Hello! I am your AI Legal Assistant for everyday money recovery in India under ₹50 Lakh.\n\n"
                                    "I specialize in:\n"
                                    "1. 🏠 **Residential Rental Deposits** (Security deposit refund from landlord)\n"
                                    "2. 🛍️ **Consumer Refunds** (Defective goods / deficient services under Consumer Protection Act 2019)\n"
                                    "3. 💼 **Unpaid Salaries** (Pending salary / final settlement under Code on Wages 2019)\n\n"
                                    "Please describe what happened (who owes you money, the amount, city/state, and key dates) via text or voice below."
                                )
                            }
                        ],
                        elem_classes="chatbot-wrapper",
                        height=480,
                    )

                    with gr.Row():
                        txt_input = gr.Textbox(
                            placeholder="Type your dispute details or reply to questions...",
                            show_label=False,
                            container=False,
                            scale=8,
                        )
                        send_btn = gr.Button("Send", variant="primary", scale=2)

                    # Voice Input
                    with gr.Group(elem_classes="voice-input-card"):
                        gr.HTML("""
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                          <span style="font-size:12px; font-weight:700; color:#1E1B4B; display:flex; align-items:center; gap:6px;">
                            <span>🎙️ Voice Input (Microphone / Audio Upload)</span>
                          </span>
                          <span style="font-size:11px; color:#64748B;">Hindi • English • Hinglish • Regional</span>
                        </div>
                        """)
                        audio_input = gr.Audio(
                            sources=["microphone", "upload"],
                            type="filepath",
                            format="wav",
                            label="Record your problem by clicking Record",
                            show_label=False,
                            interactive=True,
                        )
                        with gr.Row():
                            send_voice_btn = gr.Button("🚀 Send Voice to AI Lawyer", variant="primary", scale=6)
                            transcribe_voice_btn = gr.Button("✍️ Transcribe to Text", variant="secondary", scale=4)
                            clear_voice_btn = gr.Button("🗑️ Clear", size="sm", scale=2)
                        voice_status = gr.HTML(value="")

                    with gr.Row(visible=False) as action_bar:
                        confirm_btn = gr.Button("✓ Confirm Dispute Facts", variant="secondary", size="sm")
                        notice_cure_days_dropdown = gr.Dropdown(
                            choices=[7, 15, 30],
                            value=15,
                            label="Notice Deadline (Days)",
                            scale=3,
                        )
                        draft_btn = gr.Button("📝 Generate Legal Notice", variant="primary", size="sm")
                        practice_btn = gr.Button("🎭 Practice Dialogue (Argue with Opponent)", variant="secondary", size="sm")

            # Column 2: Case Assessment & Notice Drafter (50%)
            with gr.Column(scale=6):
                # Panel 1: Case Assessment
                with gr.Group(elem_classes="panel-card"):
                    gr.HTML("""
                    <div>
                      <h3 class="panel-header-title">Case Assessment</h3>
                      <p class="panel-header-sub">Fact summary, legal risks, and strategic next steps.</p>
                    </div>
                    """)
                    analysis_cards_html = gr.HTML(
                        value=render_case_analysis_cards(
                            ["Awaiting dispute details...", "Describe your situation in the chat or voice input"],
                            ["Statutory provisions will be evaluated automatically", "Limitation period monitored"],
                            ["Remedy roadmap generated upon intake", "Custom legal notice prepared with 15-day cure period"]
                        )
                    )

                # Panel 2: Recovery Roadmap & Deadlines
                with gr.Group(elem_classes="panel-card"):
                    with gr.Row():
                        with gr.Column(scale=8):
                            gr.HTML("""
                            <div>
                              <h3 class="panel-header-title">Recovery Roadmap & Deadlines</h3>
                              <p class="panel-header-sub">Statutory 4-step recovery ladder and verified limitation clocks.</p>
                            </div>
                            """)
                        with gr.Column(scale=4):
                            download_plan_btn = gr.Button("📥 Download Plan (.docx)", size="sm", variant="secondary")
                    action_plan_file = gr.File(label="Action Plan (.docx)", visible=False)
                    action_plan_html = gr.HTML(
                        value=render_action_plan_dashboard(
                            generate_action_plan(CaseFile()),
                            CaseFile()
                        )
                    )

                # Panel 3: Document Viewer & Legal Notice (.docx download)
                with gr.Group(elem_classes="panel-card"):
                    with gr.Row():
                        with gr.Column(scale=8):
                            gr.HTML("""
                            <div>
                              <h3 class="panel-header-title">Legal Notice / Demand Letter</h3>
                              <p class="panel-header-sub">Formal statutory demand letter with customizable cure period.</p>
                            </div>
                            """)
                        with gr.Column(scale=4):
                            download_file = gr.File(label="Download .docx", visible=False)

                    doc_preview_html = gr.HTML(
                        value=render_document_preview("")
                    )

        # ── Event Handlers: Consultation ─────────────────────────────────────

        def process_message(
            user_msg: str,
            stage: Stage,
            casefile: CaseFile,
            rules_result: Optional[RulesResult],
            language: str,
            chat_history: list,
            practice_history: list,
            practice_turns: int,
            draft_text: str,
            notice_days: int = 15,
            audio_path: Optional[str] = None,
        ):
            # Safe deserialization for Pydantic objects & enums
            if isinstance(casefile, dict):
                try:
                    casefile = CaseFile.model_validate(casefile)
                except Exception:
                    casefile = CaseFile()
            elif not isinstance(casefile, CaseFile):
                casefile = CaseFile()

            if isinstance(rules_result, dict):
                try:
                    rules_result = RulesResult.model_validate(rules_result)
                except Exception:
                    rules_result = run_rules(casefile)
            elif rules_result is not None and not isinstance(rules_result, RulesResult):
                rules_result = run_rules(casefile)

            if isinstance(stage, str):
                try:
                    stage = Stage(stage)
                except Exception:
                    stage = Stage.INTAKE

            # If text box is empty but voice note is present, transcribe audio automatically!
            if not (user_msg and user_msg.strip()) and audio_path:
                try:
                    print(f"[APP] process_message transcribing audio from: {audio_path}")
                    transcribed = transcribe(audio_path)
                    print(f"[APP] process_message transcribed: {repr(transcribed)}")
                    if transcribed:
                        user_msg = transcribed
                except Exception as e:
                    print(f"[APP] Error transcribing audio in process_message: {e}")

            if not (user_msg and user_msg.strip()):
                return (
                    chat_history, stage, casefile, rules_result, language,
                    practice_history, practice_turns, draft_text,
                    gr.update(), gr.update(), gr.update(), gr.update(),
                    gr.update(), gr.update(), gr.update(), gr.update(),
                    "", gr.update(), gr.update()
                )

            casefile.notice_cure_days = int(notice_days) if notice_days else 15

            chat_history = chat_history + [{"role": "user", "content": user_msg}]
            bot_response = ""
            new_stage = stage
            show_confirm = False
            show_draft = False
            show_practice = False
            docx_path = None

            summary_items = ["Processing inquiry..."]
            risk_items = ["Evaluating legal provisions..."]
            next_step_items = ["Formulating remedies..."]

            try:
                if stage in (Stage.WELCOME, Stage.INTAKE):
                    if stage == Stage.WELCOME:
                        language = detect_language(user_msg)
                        new_stage = Stage.INTAKE

                    intake_resp = run_intake(user_msg, casefile, language)
                    casefile = intake_resp.casefile

                    if intake_resp.escalation_flag:
                        casefile.escalation_flag = intake_resp.escalation_flag
                        bot_response = escalation_message(intake_resp.escalation_flag, language)
                        new_stage = Stage.ESCALATED
                        summary_items = [f"Escalated matter: {intake_resp.escalation_flag}"]
                        risk_items = ["Outside automated recovery scope", "Criminal / Family / Complex property"]
                        next_step_items = ["Contact NALSA Legal Aid: 15100", "Emergency police: 112", "National Consumer Helpline: 1915"]

                    else:
                        # Check if essential facts are collected
                        has_essentials = bool(casefile.category and casefile.amount_claimed and casefile.opponent_name)
                        if not has_essentials:
                            questions_list = []
                            if getattr(intake_resp, 'next_question_or_clarification', None):
                                questions_list = [intake_resp.next_question_or_clarification]
                            elif getattr(intake_resp, 'next_questions', None):
                                if isinstance(intake_resp.next_questions, list):
                                    questions_list = intake_resp.next_questions
                                else:
                                    questions_list = [str(intake_resp.next_questions)]

                            questions_block = "\n".join(f"• {q.strip('• ')}" for q in questions_list if q.strip())
                            card = format_casefile_card(casefile)
                            if questions_block:
                                prompt_clarify = "कृपया निम्नलिखित जानकारी बताएं ताकि हम आपकी कानूनी सलाह और लीगल नोटिस तैयार कर सकें:" if (language and language.lower().startswith('hi')) else "To formulate your grounded legal advice and draft, please clarify:"
                                bot_response = f"{card}\n\n**{prompt_clarify}**\n{questions_block}"
                            else:
                                bot_response = card
                            new_stage = Stage.INTAKE
                            summary_items = [f"Dispute Type: {casefile.category.value if casefile.category else 'Identifying...'}"]
                            risk_items = ["Awaiting claim amount & opponent details"]
                            next_step_items = ["Provide missing details via chat or voice"]
                        else:
                            rules_result = run_rules(casefile)
                            if rules_result.escalation:
                                bot_response = escalation_message(rules_result.escalation, language)
                                new_stage = Stage.ESCALATED
                                summary_items = [f"Escalated matter: {rules_result.escalation}"]
                                risk_items = ["Outside automated recovery scope"]
                                next_step_items = ["Contact NALSA Legal Aid: 15100"]
                            else:
                                advice = run_advisor(casefile, rules_result, language)
                                bot_response = render_citations(advice)

                                draft_text = run_drafter(casefile, rules_result, language)
                                docx_path = generate_docx(draft_text, casefile)

                                summary_items, risk_items, next_step_items = parse_advice_sections(advice)
                                new_stage = Stage.ADVICE
                                show_draft = True
                                show_practice = True

                elif stage == Stage.CONFIRM or (stage == Stage.INTAKE and user_msg.strip().lower() in ("yes", "confirm", "ok", "haan", "ha")):
                    rules_result = run_rules(casefile)
                    if rules_result.escalation:
                        bot_response = escalation_message(rules_result.escalation, language)
                        new_stage = Stage.ESCALATED
                    else:
                        advice = run_advisor(casefile, rules_result, language)
                        bot_response = render_citations(advice)
                        draft_text = run_drafter(casefile, rules_result, language)
                        docx_path = generate_docx(draft_text, casefile)

                        summary_items, risk_items, next_step_items = parse_advice_sections(advice)
                        new_stage = Stage.ADVICE
                        show_draft = True
                        show_practice = True

                elif stage == Stage.ADVICE:
                    if user_msg.strip().lower() in ("draft", "generate", "notice", "letter"):
                        draft_text = run_drafter(casefile, rules_result, language)
                        docx_path = generate_docx(draft_text, casefile)
                        bot_response = f"**Formal Notice Draft**\n\n{render_citations(draft_text)}"
                        new_stage = Stage.DRAFT
                        show_draft = True
                        show_practice = True
                    else:
                        advice = run_advisor(casefile, rules_result, language)
                        bot_response = render_citations(advice)
                        summary_items, risk_items, next_step_items = parse_advice_sections(advice)
                        show_draft = True
                        show_practice = True

                elif stage == Stage.PRACTICE:
                    if user_msg.strip().lower() in ("stop", "exit", "quit", "end", "bas", "khatam"):
                        user_statements = [p["user"] for p in practice_history if "user" in p]
                        last_arg = user_statements[-1] if user_statements else ""
                        arg_ctx = f"Their key counter-argument was: '{last_arg}'." if last_arg else "The citizen concluded the practice session early."
                        feedback_prompt = (
                            f"The citizen is preparing to negotiate with their {casefile.opponent_type or 'counterparty'}, "
                            f"{casefile.opponent_name or 'the opponent'}, for a claim of ₹{casefile.amount_claimed or 0:,.0f} "
                            f"regarding {casefile.category.value if casefile.category else 'money dispute'}.\n"
                            f"{arg_ctx}\n\n"
                            "Provide exactly 3 constructive, actionable negotiation tips in clean bullet points:\n"
                            "1. What was effective or recommended phrasing\n"
                            "2. Key statutory leverage to cite (e.g. normal wear and tear under Section 108 Transfer of Property Act, or contract breach)\n"
                            "3. Essential documentary evidence to present on the spot"
                        )
                        tips = chat([{"role": "user", "content": feedback_prompt}], temperature=0.3, max_tokens=450)
                        bot_response = f"🎭 **Practice Session Concluded — Negotiation Feedback:**\n\n{tips}\n\n*(Ready to send your formal notice? Check the Document Viewer in the right panel.)*"
                        new_stage = Stage.ADVICE
                        show_draft = True
                        show_practice = True
                    else:
                        practice_turns += 1
                        practice_history.append({"user": user_msg})
                        if practice_turns >= 4:
                            user_statements = [p["user"] for p in practice_history if "user" in p]
                            last_arg = user_statements[-1] if user_statements else user_msg
                            feedback_prompt = (
                                f"The citizen finished 4 practice rounds negotiating against their {casefile.opponent_type or 'counterparty'}, "
                                f"{casefile.opponent_name or 'the opponent'}, claiming ₹{casefile.amount_claimed or 0:,.0f} "
                                f"regarding {casefile.category.value if casefile.category else 'money dispute'}.\n"
                                f"Their key counter-argument was: '{last_arg}'.\n\n"
                                "Provide exactly 3 concise, actionable negotiation tips in bullet points:\n"
                                "1. What was effective in their approach\n"
                                "2. How to counter bad-faith excuses\n"
                                "3. Key documentary evidence to present before formal notice/court"
                            )
                            tips = chat([{"role": "user", "content": feedback_prompt}], temperature=0.3, max_tokens=450)
                            bot_response = f"🎭 **Practice Dialogue Completed (4/4 Rounds):**\n\n{tips}\n\n*(Your formal Legal Notice is ready to download in Document Viewer!)*"
                            new_stage = Stage.ADVICE
                            show_draft = True
                            show_practice = True
                        else:
                            opponent_prompt = (
                                f"Roleplay as {casefile.opponent_name or 'the opponent'} ({casefile.opponent_type or 'landlord/seller/employer'}). "
                                f"The other person says: '{user_msg}'. "
                                "Push back realistically, deny or offer low settlement, cite standard excuses ('flat damages', 'company return policy', 'notice period deduction'). "
                                f"Stay civil. Speak in {language}. Keep under 3 sentences."
                            )
                            opp_reply = chat([{"role": "user", "content": opponent_prompt}], temperature=0.4, max_tokens=150)
                            practice_history.append({"opponent": opp_reply})
                            bot_response = f"**{casefile.opponent_name or 'Opponent'}:** \"{opp_reply}\"\n\n*(Round {practice_turns}/4 • Reply to counter-argue, or type 'stop' to finish and get feedback)*"
                            new_stage = Stage.PRACTICE
                            show_practice = True

                elif stage == Stage.ESCALATED:
                    intake_resp = run_intake(user_msg, CaseFile(), language)
                    if intake_resp.escalation_flag:
                        bot_response = (
                            "This inquiry remains outside standard civil recovery scope. "
                            "Please contact NALSA (15100), National Consumer Helpline (1915), or emergency services (112)."
                        )
                    else:
                        casefile = intake_resp.casefile
                        if (casefile.category and casefile.amount_claimed and casefile.opponent_name):
                            rules_result = run_rules(casefile)
                            advice = run_advisor(casefile, rules_result, language)
                            bot_response = render_citations(advice)
                            draft_text = run_drafter(casefile, rules_result, language)
                            docx_path = generate_docx(draft_text, casefile)
                            summary_items, risk_items, next_step_items = parse_advice_sections(advice)
                            new_stage = Stage.ADVICE
                            show_draft = True
                            show_practice = True
                        else:
                            bot_response = format_casefile_card(casefile)
                            new_stage = Stage.INTAKE

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                bot_response = f"⚠️ Notice: Unable to complete legal analysis ({str(e)[:140]}). Please click Send to retry."

            if bot_response:
                chat_history = chat_history + [{"role": "assistant", "content": bot_response}]

            cards_html_update = render_case_analysis_cards(summary_items, risk_items, next_step_items, casefile=casefile)
            doc_html_update = render_document_preview(draft_text)
            plan_data = generate_action_plan(casefile, rules_result)
            action_plan_update = render_action_plan_dashboard(plan_data, casefile)

            return (
                chat_history,
                new_stage,
                casefile,
                rules_result,
                language,
                practice_history,
                practice_turns,
                draft_text,
                cards_html_update,
                doc_html_update,
                action_plan_update,
                gr.update(visible=show_confirm or show_draft or show_practice),
                gr.update(visible=show_confirm),
                gr.update(visible=show_draft),
                gr.update(visible=show_practice),
                gr.update(visible=bool(docx_path), value=docx_path) if docx_path else gr.update(),
                "",
                None,
                "<div style='font-size:11px; color:#15803D; font-weight:600; padding:4px 8px; background:#DCFCE7; border-radius:6px;'>✓ Voice message processed and sent to AI Lawyer!</div>" if audio_path else ""
            )

        all_inputs = [
            txt_input, state_stage, state_casefile,
            state_rules, state_language, chatbot,
            state_practice_history, state_practice_turns, state_draft_text,
            notice_cure_days_dropdown,
            audio_input,
        ]
        all_outputs = [
            chatbot, state_stage, state_casefile, state_rules,
            state_language, state_practice_history, state_practice_turns,
            state_draft_text, analysis_cards_html, doc_preview_html,
            action_plan_html, action_bar, confirm_btn, draft_btn,
            practice_btn, download_file, txt_input,
            audio_input, voice_status,
        ]

        send_btn.click(process_message, inputs=all_inputs, outputs=all_outputs)
        txt_input.submit(process_message, inputs=all_inputs, outputs=all_outputs)
        send_voice_btn.click(process_message, inputs=all_inputs, outputs=all_outputs)

        def on_start_practice(casefile, language, chat_history):
            if isinstance(casefile, dict):
                try:
                    casefile = CaseFile.model_validate(casefile)
                except Exception:
                    casefile = CaseFile()
            elif not isinstance(casefile, CaseFile):
                casefile = CaseFile()

            opponent_name = casefile.opponent_name or "the counterparty"
            opponent_type = casefile.opponent_type or ("landlord" if casefile.category == CaseCategory.DEPOSIT else "seller")
            prompt = (
                f"You are roleplaying as {opponent_name} ({opponent_type}) in an Indian money dispute of ₹{casefile.amount_claimed or 0:,.0f}. "
                f"Give a realistic opening pushback or denial. Keep it under 2 sentences in {language}."
            )
            opening_challenge = chat([{"role": "user", "content": prompt}], temperature=0.4, max_tokens=120)
            bot_msg = (
                f"🎭 **Practice Dialogue Mode Activated**\n\n"
                f"*(I am now roleplaying as your {opponent_type}, **{opponent_name}**. Practice arguing your claim before you serve the legal notice. "
                "Type your counter-argument below, or type **'stop'** at any time to receive negotiation tips.)*\n\n"
                f"**{opponent_name}:** \"{opening_challenge}\""
            )
            return (
                chat_history + [{"role": "assistant", "content": bot_msg}],
                Stage.PRACTICE,
                [],
                1,
                gr.update(visible=True),
                gr.update(visible=True)
            )

        practice_btn.click(
            on_start_practice,
            inputs=[state_casefile, state_language, chatbot],
            outputs=[chatbot, state_stage, state_practice_history, state_practice_turns, action_bar, practice_btn]
        )

        def on_direct_draft(casefile, rules_result, language, notice_days):
            try:
                print(f"[APP] on_direct_draft called with notice_days={notice_days}")
                if isinstance(casefile, dict):
                    try:
                        casefile = CaseFile.model_validate(casefile)
                    except Exception:
                        casefile = CaseFile()
                elif not isinstance(casefile, CaseFile):
                    casefile = CaseFile()

                if isinstance(rules_result, dict):
                    try:
                        rules_result = RulesResult.model_validate(rules_result)
                    except Exception:
                        rules_result = run_rules(casefile)
                elif not isinstance(rules_result, RulesResult):
                    rules_result = run_rules(casefile)

                if casefile and notice_days:
                    casefile.notice_cure_days = int(notice_days)

                draft_text = run_drafter(casefile, rules_result, language or "English")
                docx_path = generate_docx(draft_text, casefile)
                print(f"[APP] on_direct_draft generated docx: {docx_path}")
                return render_document_preview(draft_text), gr.update(value=docx_path, visible=True), draft_text
            except Exception as e:
                logger.error(f"[APP] Error in on_direct_draft: {e}", exc_info=True)
                return f"<div style='color:#DC2626; padding:12px; background:#FEF2F2; border-radius:8px;'>⚠️ Notice generation error: {str(e)[:140]}. Please click Generate Legal Notice to retry.</div>", gr.update(), ""

        draft_btn.click(
            on_direct_draft,
            inputs=[state_casefile, state_rules, state_language, notice_cure_days_dropdown],
            outputs=[doc_preview_html, download_file, state_draft_text]
        )

        def on_voice_transcribe(audio_path, current_text):
            if not audio_path:
                return current_text, "<div style='font-size:11px; color:#64748B;'>🎙️ Click Record to speak.</div>"
            try:
                transcript_text = transcribe(audio_path)
                if transcript_text:
                    merged = f"{current_text} {transcript_text}".strip() if current_text else transcript_text
                    safe_preview = html.escape(transcript_text[:90])
                    return merged, f"<div style='font-size:11px; color:#15803D; font-weight:600; padding:6px 10px; background:#DCFCE7; border-radius:6px;'>✓ Voice Transcribed: \"{safe_preview}...\"<br>👉 Click <strong>🚀 Send Voice to AI Lawyer</strong> or <strong>Send</strong> to submit!</div>"
                else:
                    return current_text, "<div style='font-size:11px; color:#D97706;'>No speech detected in audio. Please speak clearly into your mic and click Stop when done.</div>"
            except Exception as e:
                return current_text, f"<div style='font-size:11px; color:#6B7280;'>Voice note: {str(e)[:80]}. Please type directly.</div>"

        audio_input.change(
            on_voice_transcribe,
            inputs=[audio_input, txt_input],
            outputs=[txt_input, voice_status]
        )

        transcribe_voice_btn.click(
            on_voice_transcribe,
            inputs=[audio_input, txt_input],
            outputs=[txt_input, voice_status]
        )

        clear_voice_btn.click(
            lambda: (None, "<div style='font-size:11px; color:#64748B;'>🎙️ Audio cleared. Click Record to speak again.</div>"),
            outputs=[audio_input, voice_status]
        )

        def on_confirm_facts(stage, casefile, rules, lang, history, p_hist, p_turns, draft, days):
            if isinstance(casefile, dict):
                try:
                    casefile = CaseFile.model_validate(casefile)
                except Exception:
                    casefile = CaseFile()
            if isinstance(rules, dict):
                try:
                    rules = RulesResult.model_validate(rules)
                except Exception:
                    rules = None
            return process_message(
                "yes", stage, casefile, rules, lang, history, p_hist, p_turns, draft, days, None
            )

        confirm_btn.click(
            on_confirm_facts,
            inputs=[
                state_stage, state_casefile, state_rules, state_language, chatbot,
                state_practice_history, state_practice_turns, state_draft_text,
                notice_cure_days_dropdown
            ],
            outputs=all_outputs
        )

        # ── Event Handlers: Recovery Action Plan ─────────────────────────────

        def on_download_plan(casefile, rules_result):
            if isinstance(casefile, dict):
                try:
                    casefile = CaseFile.model_validate(casefile)
                except Exception:
                    casefile = CaseFile()
            elif not isinstance(casefile, CaseFile):
                casefile = CaseFile()

            if isinstance(rules_result, dict):
                try:
                    rules_result = RulesResult.model_validate(rules_result)
                except Exception:
                    rules_result = run_rules(casefile)
            elif not isinstance(rules_result, RulesResult):
                rules_result = run_rules(casefile)

            plan = generate_action_plan(casefile, rules_result)
            docx_path = generate_action_plan_docx(plan, casefile)
            return gr.update(value=docx_path, visible=True)

        download_plan_btn.click(
            on_download_plan,
            inputs=[state_casefile, state_rules],
            outputs=[action_plan_file]
        )

    return app


if __name__ == "__main__":
    print("[APP] Initializing NyaySaathi (न्याय साथी) Gradio UI...", flush=True)
    app = create_app()
    print("[APP] Launching Gradio server on http://0.0.0.0:7860...", flush=True)
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=True,
        show_error=True,
        css=DASHBOARD_CSS,
        allowed_paths=[str(Path(__file__).parent / "outputs")],
    )
