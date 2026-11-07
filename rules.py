"""Deterministic rules engine — no LLM, pure code logic.

Handles: escalation detection, limitation-period estimation, forum selection,
missing-proof checklist, and doc-type mapping.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from schemas import (
    CaseCategory,
    CaseFile,
    DocType,
    Forum,
    RulesResult,
    MissingFactItem,
)


# ── Escalation keywords ─────────────────────────────────────────────────────

ESCALATION_KEYWORDS = [
    "threat", "violence", "police", "fir", "murder", "assault", "abuse",
    "harass", "stalk", "kidnap", "cheat", "fraud", "cyber", "hack",
    "divorce", "maintenance", "custody", "matrimonial", "dowry",
    "property title", "eviction", "government employee", "psu",
    "court case", "already filed", "sub judice", "hearing date",
    "criminal", "ipc", "bns", "arrest",
    "dangerous", "weapon", "life at risk", "suicide",
    "धमकी", "हिंसा", "पुलिस", "एफआईआर", "तलाक",
]

AMOUNT_CEILING = 50_00_000  # ₹50 lakh for District Consumer Commission


def run_rules(casefile: CaseFile) -> RulesResult:
    """Run all deterministic checks on a confirmed CaseFile."""
    result = RulesResult()

    # ── 1. Escalation checks ─────────────────────────────────────────────
    escalation = _check_escalation(casefile)
    if escalation:
        result.escalation = escalation
        result.forum = Forum.OUT_OF_SCOPE
        return result

    # ── 2. Amount check ──────────────────────────────────────────────────
    if casefile.amount_claimed and casefile.amount_claimed > AMOUNT_CEILING:
        result.escalation = (
            f"Claim of ₹{casefile.amount_claimed:,.0f} exceeds ₹50 lakh District Commission limit. "
            "A lawyer is needed for the appropriate higher forum."
        )
        result.amount_in_range = False
        result.forum = Forum.OUT_OF_SCOPE
        return result

    # ── 3. Forum + doc type ──────────────────────────────────────────────
    if casefile.category == CaseCategory.DEPOSIT:
        result.forum = Forum.CIVIL_COURT
        result.doc_type = DocType.LEGAL_NOTICE
    elif casefile.category == CaseCategory.CONSUMER:
        result.forum = Forum.CONSUMER_COMMISSION
        result.doc_type = DocType.CONSUMER_COMPLAINT
    elif casefile.category == CaseCategory.SALARY:
        result.forum = Forum.LABOUR_AUTHORITY
        result.doc_type = DocType.SALARY_DEMAND
    else:
        result.forum = Forum.OUT_OF_SCOPE
        result.escalation = "This type of dispute is outside what I can help with."
        return result

    # ── 4. Limitation period estimate ────────────────────────────────────
    limitation = _estimate_limitation(casefile)
    if limitation:
        result.limitation_estimate = limitation["text"]
        result.limitation_warning = limitation["warning"]

    # ── 5. Missing proof checklist ───────────────────────────────────────
    result.missing_proof = _check_missing_proof(casefile)

    return result


# ── Helpers ──────────────────────────────────────────────────────────────────

def _check_escalation(cf: CaseFile) -> Optional[str]:
    """Scan for out-of-scope / dangerous situations."""
    # Explicit escalation flag from intake
    if cf.escalation_flag:
        return cf.escalation_flag

    # Keyword scan on story
    searchable = " ".join(
        filter(None, [cf.story_summary, cf.what_tried, cf.opponent_type])
    ).lower()

    for kw in ESCALATION_KEYWORDS:
        if kw in searchable:
            return f"Detected sensitive topic ('{kw}'). This needs a real lawyer, not an AI tool."

    return None


def _estimate_limitation(cf: CaseFile) -> Optional[dict]:
    """Estimate limitation period based on category and dates."""
    if not cf.key_dates:
        return None

    today = date.today()

    # Find the most relevant date
    cause_date = None
    for key in ["vacated", "returned", "last_working_day", "refund_due_date",
                 "complaint_date", "purchase_date", "cancellation_date",
                 "salary_due_date", "termination_date"]:
        if key in cf.key_dates:
            try:
                cause_date = date.fromisoformat(cf.key_dates[key])
                break
            except (ValueError, TypeError):
                continue

    # If no specific date found, try the latest date
    if cause_date is None:
        for val in reversed(list(cf.key_dates.values())):
            try:
                cause_date = date.fromisoformat(str(val))
                break
            except (ValueError, TypeError):
                continue

    if cause_date is None:
        return None

    # Limitation periods (approximate)
    if cf.category == CaseCategory.CONSUMER:
        limit_years = 2  # CPA 2019: 2 years from cause of action
        limit_label = "2 years (Consumer Protection Act, 2019)"
    elif cf.category == CaseCategory.SALARY:
        limit_years = 3  # Code on Wages, 2019: generally 3 years
        limit_label = "3 years (Code on Wages, 2019 — state rules may vary)"
    elif cf.category == CaseCategory.DEPOSIT:
        limit_years = 3  # General civil limitation: 3 years
        limit_label = "3 years (Limitation Act, 1963 — money recovery)"
    else:
        return None

    deadline = cause_date + timedelta(days=limit_years * 365)
    days_remaining = (deadline - today).days
    approximate_note = " (dates are approximate)" if cf.dates_approximate else ""

    text = (
        f"Limitation period: {limit_label}.\n"
        f"Cause of action date: {cause_date.isoformat()}{approximate_note}.\n"
        f"Estimated deadline: {deadline.isoformat()}.\n"
        f"Days remaining: {days_remaining}."
    )

    warning = days_remaining < 90  # Warn if less than 3 months

    if days_remaining < 0:
        text += (
            "\n⚠️ The limitation period may have EXPIRED. "
            "Please consult a lawyer urgently — there may be exceptions or ways to apply for condonation of delay."
        )
        warning = True

    return {"text": text, "warning": warning}


def _check_missing_proof(cf: CaseFile) -> list[str]:
    """Return a checklist of proof items that would help the case."""
    available = set(p.lower() for p in (cf.proof_available or []))
    missing = []

    # Common proof for all categories
    common_proof = {
        "written communication": [
            "emails", "whatsapp", "sms", "messages", "letter", "notice",
            "chat", "screenshot"
        ],
    }

    category_proof: dict[CaseCategory, list[tuple[str, list[str]]]] = {
        CaseCategory.DEPOSIT: [
            ("Rental agreement / lease deed", ["agreement", "lease", "rent agreement", "contract"]),
            ("Deposit payment receipt / bank transfer proof", ["receipt", "bank statement", "transfer", "upi"]),
            ("Photos of property condition at move-in", ["photo", "picture", "image", "move-in"]),
            ("Photos of property condition at move-out", ["photo", "picture", "image", "move-out", "vacating"]),
            ("Communication about deposit return", ["whatsapp", "email", "sms", "chat", "message"]),
        ],
        CaseCategory.CONSUMER: [
            ("Purchase invoice / order confirmation", ["invoice", "bill", "order", "receipt", "confirmation"]),
            ("Product/service complaint details (screenshots, emails)", ["screenshot", "complaint", "email"]),
            ("Return tracking / refund acknowledgment", ["tracking", "return", "refund"]),
            ("Company response to complaint (if any)", ["response", "reply", "customer care"]),
        ],
        CaseCategory.SALARY: [
            ("Offer letter / appointment letter", ["offer letter", "appointment", "joining"]),
            ("Salary slips", ["salary slip", "pay slip", "payslip"]),
            ("Bank statements showing salary credits", ["bank statement", "bank", "salary credit"]),
            ("Employment contract", ["contract", "employment agreement"]),
            ("Resignation letter / termination letter", ["resignation", "termination"]),
            ("Communication about pending salary", ["email", "whatsapp", "message", "hr"]),
        ],
    }

    # Check category-specific proof
    proofs_to_check = category_proof.get(cf.category, [])
    for proof_name, keywords in proofs_to_check:
        found = any(kw in term for term in available for kw in keywords)
        if not found:
            missing.append(proof_name)

    return missing


def check_information_sufficiency(cf: CaseFile) -> tuple[bool, list[str], str]:
    """Check if the casefile contains sufficient information for a definitive legal assessment.
    
    Returns:
        is_sufficient: bool
        missing_items: list of missing fields
        warning_html: formatted warning banner if insufficient, else success banner
    """
    missing = []
    
    if not cf.category:
        missing.append("Dispute Category (Specify whether this is a Rental Deposit, Consumer Refund, or Unpaid Salary)")
    
    if not cf.amount_claimed or cf.amount_claimed <= 0:
        missing.append("Disputed Amount (Critical for pecuniary jurisdiction: < ₹50 Lakh for District Consumer Commission)")
        
    if not cf.opponent_name or cf.opponent_name.strip().lower() in ("opponent", "counterparty", "identified in document", "company", "landlord", "employer", ""):
        missing.append("Counterparty Legal Name (Required for legal notice recipient address & corporate identity)")
        
    if not cf.city and not cf.state:
        missing.append("Territorial Jurisdiction / Location (Required to identify local Rent Authority, Labour Commissioner, or District Commission)")
        
    if not cf.proof_available or len(cf.proof_available) == 0:
        missing.append("Documentary Proof / Transaction Records (Necessary to satisfy the burden of proof under Indian Law)")

    is_sufficient = len(missing) == 0
    if not is_sufficient:
        items_html = "".join(f"<li style='margin-bottom:4px; font-weight:600;'>{m}</li>" for m in missing)
        warning_html = f"""
        <div style="background:#FFFBEB; border:1px solid #FDE68A; border-left:4px solid #D97706; border-radius:8px; padding:12px 16px; margin-bottom:14px; box-shadow:0 1px 2px rgba(0,0,0,0.02);">
          <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:16px;">⚠️</span>
              <span style="font-size:13px; font-weight:700; color:#92400E;">INSUFFICIENT INFORMATION WARNING</span>
              <span style="font-size:10px; background:#FEF3C7; color:#B45309; padding:2px 7px; border-radius:10px; font-weight:700;">Action Required</span>
            </div>
            <span style="font-size:10px; color:#B45309; font-weight:600;">{len(missing)} Key Details Pending</span>
          </div>
          <div style="font-size:12px; color:#78350F; line-height:1.5;">
            The following essential legal parameters are missing or unconfirmed:
            <ul style="margin:6px 0; padding-left:20px; font-size:11px; color:#92400E;">
              {items_html}
            </ul>
            <strong>Legal Implication:</strong> Under Indian civil law, statutory limitation periods (Limitation Act 1963 / Section 69 CPA 2019), pecuniary forum ceilings (Section 34 CPA 2019), and valid notice service depend strictly on these facts.
            <div style="margin-top:6px; font-size:11px; color:#B45309;">
              💡 <em>Please confirm these details in Chat or preserve transaction proofs before issuing a formal notice.</em>
            </div>
          </div>
        </div>
        """
    else:
        warning_html = f"""
        <div style="background:#F0FDF4; border:1px solid #BBF7D0; border-left:4px solid #16A34A; border-radius:8px; padding:10px 14px; margin-bottom:14px;">
          <div style="display:flex; align-items:center; justify-content:space-between;">
            <div style="display:flex; align-items:center; gap:8px; font-size:12px; font-weight:700; color:#14532D;">
              <span>✓ Information Sufficiency Confirmed</span>
              <span style="font-size:10px; background:#DCFCE7; color:#15803D; padding:1px 6px; border-radius:10px; font-weight:600;">Pecuniary & Territorial Verified</span>
            </div>
            <span style="font-size:11px; color:#166534;">Statutory Grounding Ready</span>
          </div>
        </div>
        """

    return is_sufficient, missing, warning_html


# ── Priority 1: Dynamic Fact Extraction Engine ───────────────────────────────

def get_dynamic_missing_facts(cf: CaseFile) -> list[MissingFactItem]:
    """Identify missing facts and generate targeted follow-up questions for the user.

    Covers Priority 1: Dynamic Fact Extraction.
    """
    cat = cf.category
    missing: list[MissingFactItem] = []

    # 1. Base missing facts
    if not cf.category:
        missing.append(MissingFactItem(
            key="category",
            question="What is the nature of your dispute: a withheld tenancy security deposit, an e-commerce/consumer refund, or unpaid salary?",
            legal_relevance="Determines governing statute: Indian Contract Act 1872 vs Consumer Protection Act 2019 vs Code on Wages 2019.",
            is_critical=True
        ))
        return missing

    if not cf.amount_claimed or cf.amount_claimed <= 0:
        missing.append(MissingFactItem(
            key="amount",
            question="What is the exact amount owed or withheld in rupees (₹)?",
            legal_relevance="Required to establish pecuniary jurisdiction (e.g. up to ₹50 Lakh for District Consumer Commission under CPA 2019).",
            is_critical=True
        ))

    if not cf.opponent_name or cf.opponent_name.strip().lower() in ("opponent", "counterparty", "identified in document", "company", "landlord", "employer", ""):
        opp_label = "landlord" if cat == CaseCategory.DEPOSIT else ("seller or company" if cat == CaseCategory.CONSUMER else "employer or company")
        missing.append(MissingFactItem(
            key="opponent_name",
            question=f"What is the full legal name of the {opp_label} who owes you money?",
            legal_relevance="A formal legal notice or statutory complaint must be issued against the precise legal individual or corporate entity.",
            is_critical=True
        ))

    proof_str = " ".join(cf.proof_available or []).lower()
    dates_dict = cf.key_dates or {}
    story = (cf.story_summary or "").lower()

    if cat == CaseCategory.DEPOSIT:
        # Check written agreement
        has_agreement = any(term in proof_str or term in story for term in ("agreement", "lease", "rent contract", "tenancy agreement"))
        if not has_agreement:
            missing.append(MissingFactItem(
                key="written_agreement",
                question="Did you sign a written rental or lease agreement with your landlord?",
                legal_relevance="Determines whether deposit refund terms are governed by contract terms (Sec 73 Contract Act) or oral tenancy presumptions.",
                is_critical=True
            ))

        # Check vacate / handover date
        has_vacate = cf.cause_of_action_date or any(k in dates_dict for k in ("vacated", "handover", "moved_out", "cause_of_action"))
        if not has_vacate:
            missing.append(MissingFactItem(
                key="vacate_date",
                question="On which date did you vacate the property and hand over the keys to the landlord?",
                legal_relevance="Triggers the cause of action and starts the 3-year clock under the Limitation Act, 1963.",
                is_critical=True
            ))

        # Check deposit payment proof
        has_payment_proof = any(term in proof_str or term in story for term in ("receipt", "bank transfer", "upi", "neft", "statement", "passbook", "slip"))
        if not has_payment_proof:
            missing.append(MissingFactItem(
                key="deposit_proof",
                question="Do you have bank transfer records, UPI transaction IDs, or a payment receipt showing the deposit paid?",
                legal_relevance="Section 101/102 Bharatiya Sakshya Adhiniyam, 2023 (Indian Evidence Act) places the burden of proof on the claimant.",
                is_critical=False
            ))

        # Check deduction reason
        has_reason = any(term in story for term in ("damage", "paint", "cleaning", "maintenance", "deduct", "repair", "bills", "refuse"))
        if not has_reason:
            missing.append(MissingFactItem(
                key="deduction_reason",
                question="What specific reason did your landlord give for deducting or withholding your deposit?",
                legal_relevance="Section 108(m) Transfer of Property Act shields tenants against unfair deductions for normal wear and tear.",
                is_critical=False
            ))

    elif cat == CaseCategory.CONSUMER:
        # Check purchase/order date
        has_purchase_date = cf.cause_of_action_date or any(k in dates_dict for k in ("purchase", "order", "delivery", "cause_of_action"))
        if not has_purchase_date:
            missing.append(MissingFactItem(
                key="purchase_date",
                question="On what date did you purchase the product or order the service?",
                legal_relevance="Section 69 of the Consumer Protection Act, 2019 sets a strict 2-year limitation period from the date the cause of action arose.",
                is_critical=True
            ))

        # Check invoice/order ID
        has_invoice = any(term in proof_str or term in story for term in ("invoice", "bill", "order id", "receipt", "booking id", "ticket"))
        if not has_invoice:
            missing.append(MissingFactItem(
                key="order_invoice",
                question="Do you have the tax invoice, cash memo, or order ID from the seller or platform?",
                legal_relevance="Establishes proof of consumer relationship under Section 2(7) of the Consumer Protection Act, 2019.",
                is_critical=True
            ))

        # Check grievance attempt
        has_grievance = any(term in story or term in (cf.what_tried or "").lower() for term in ("support", "ticket", "email", "complaint", "nch", "1915", "care"))
        if not has_grievance:
            missing.append(MissingFactItem(
                key="grievance_attempt",
                question="Did you lodge a complaint with customer support or the National Consumer Helpline (1915), and what was their response?",
                legal_relevance="Demonstrates deficiency of service under Section 2(11) CPA 2019 and exhausts pre-litigation customer resolution channels.",
                is_critical=False
            ))

    elif cat == CaseCategory.SALARY:
        # Check last working day / resignation date
        has_resignation_date = cf.cause_of_action_date or any(k in dates_dict for k in ("resignation", "termination", "lwd", "last_working_day", "cause_of_action"))
        if not has_resignation_date:
            missing.append(MissingFactItem(
                key="last_working_day",
                question="What was your last working day or official resignation date?",
                legal_relevance="Starts the statutory timeline for full & final settlement under the Code on Wages, 2019 and Limitation Act, 1963.",
                is_critical=True
            ))

        # Check offer letter or contract
        has_offer = any(term in proof_str or term in story for term in ("offer letter", "contract", "appointment letter", "agreement"))
        if not has_offer:
            missing.append(MissingFactItem(
                key="employment_contract",
                question="Do you have your signed appointment letter, offer letter, or employment contract?",
                legal_relevance="Proves the contractual employment relationship, notice period terms, and agreed monthly remuneration.",
                is_critical=True
            ))

        # Check salary slips
        has_slips = any(term in proof_str or term in story for term in ("salary slip", "payslip", "bank statement", "form 16", "pf"))
        if not has_slips:
            missing.append(MissingFactItem(
                key="salary_slips",
                question="Do you have previous pay slips or bank statements showing non-credit for the disputed months?",
                legal_relevance="Constitutes primary evidence of unpaid wages before the Labour Commissioner under Section 45 Code on Wages, 2019.",
                is_critical=False
            ))

    # Location check
    if not cf.city and not cf.state:
        missing.append(MissingFactItem(
            key="location",
            question="In which city and state did this take place?",
            legal_relevance="Required to establish territorial jurisdiction of the local District Commission, Labour Authority, or Rent Court.",
            is_critical=True
        ))

    return missing


def render_fact_discovery_html(cf: CaseFile, missing_facts: list[MissingFactItem]) -> str:
    """Render the Dynamic Fact Discovery widget in the UI."""
    total_expected = 6
    missing_count = len(missing_facts)
    gathered_count = max(0, total_expected - missing_count)
    pct = int((gathered_count / total_expected) * 100)

    if not missing_facts:
        return f"""
        <div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:8px; padding:12px; margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:6px; font-size:12px; font-weight:700; color:#15803D;">
              <span>✓ All Essential Facts Confirmed</span>
              <span style="font-size:10px; background:#DCFCE7; color:#15803D; padding:1px 6px; border-radius:10px;">100% INTAKE</span>
            </div>
            <span style="font-size:11px; color:#166534; font-weight:600;">Ready for Statutory Assessment</span>
          </div>
        </div>
        """

    questions_html = []
    for i, item in enumerate(missing_facts[:3], 1):
        crit_badge = '<span style="font-size:9px; background:#FEE2E2; color:#991B1B; padding:1px 5px; border-radius:4px; font-weight:700;">CRITICAL</span>' if item.is_critical else '<span style="font-size:9px; background:#FEF3C7; color:#92400E; padding:1px 5px; border-radius:4px; font-weight:600;">RECOMMENDED</span>'
        q_item = f"""
        <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:6px; padding:8px 10px; margin-bottom:6px;">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:3px;">
            <span style="font-size:11px; font-weight:700; color:#1E293B;">Q{i}. {item.question}</span>
            {crit_badge}
          </div>
          <div style="font-size:10px; color:#64748B;">
            <strong>Legal Impact:</strong> {item.legal_relevance}
          </div>
        </div>
        """
        questions_html.append(q_item)

    questions_rendered = "".join(questions_html)

    return f"""
    <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:12px; margin-bottom:12px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
        <div style="display:flex; align-items:center; gap:6px; font-size:11px; font-weight:700; color:#1E1B4B; text-transform:uppercase; letter-spacing:0.04em;">
          <span>🎯 Dynamic Fact Discovery</span>
          <span style="font-size:9px; background:#EFF6FF; color:#1D4ED8; padding:1px 6px; border-radius:10px; font-weight:700;">{gathered_count}/{total_expected} GATHERED</span>
        </div>
        <span style="font-size:11px; color:#D97706; font-weight:700;">{pct}% Complete</span>
      </div>

      <div style="width:100%; height:5px; background:#E2E8F0; border-radius:3px; overflow:hidden; margin-bottom:10px;">
        <div style="width:{pct}%; height:100%; background:#2563EB; border-radius:3px;"></div>
      </div>

      <div style="font-size:11px; color:#475569; margin-bottom:8px;">
        To provide legally binding notice drafting and accurate limitation calculations, the AI needs {missing_count} additional fact(s):
      </div>

      {questions_rendered}
    </div>
    """

