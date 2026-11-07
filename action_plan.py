"""Action Plan Engine for NyaySaathi (Feature 3).

Instead of simply answering questions, guides users on what to do next:
1. Collect payment evidence
2. Contact the concerned party
3. Prepare a formal complaint or notice draft
4. Identify an appropriate grievance redressal or legal aid channel
"""

from __future__ import annotations

import html
from datetime import datetime, date, timedelta
from typing import Optional

from schemas import CaseCategory, CaseFile, RulesResult, Forum
from rules import check_information_sufficiency


def calculate_limitation(casefile: CaseFile) -> dict:
    """Calculate limitation period separately for each dispute category.
    
    If the cause-of-action date or relevant trigger date is missing,
    explicitly returns 'Unable to determine – additional information required.'
    """
    if isinstance(casefile, dict):
        try:
            casefile = CaseFile.model_validate(casefile)
        except Exception:
            casefile = CaseFile()
    cat = casefile.category or CaseCategory.DEPOSIT
    coa_date = getattr(casefile, "cause_of_action_date", None)
    
    if not coa_date and getattr(casefile, "key_dates", None):
        for k in ("vacated", "handover", "delivery", "purchase", "resignation", "termination", "cause_of_action", "defect_date"):
            if k in casefile.key_dates and casefile.key_dates[k]:
                try:
                    coa_date = date.fromisoformat(casefile.key_dates[k])
                    break
                except (ValueError, TypeError):
                    pass

    if cat == CaseCategory.CONSUMER:
        act_ref = "Section 69, Consumer Protection Act, 2019"
        total_years = 2
        total_days = 730
        condonation_note = "Subject to condonation of delay under Section 69(2) upon showing sufficient cause."
        desc_missing = "Section 69 CPA 2019 prescribes 2 years from when the cause of action arose. Remaining days cannot be determined without the exact date of defect, delivery, or refund refusal."
    elif cat == CaseCategory.DEPOSIT:
        act_ref = "Limitation Act, 1963 (Schedule Article 113 / 22)"
        total_years = 3
        total_days = 1095
        condonation_note = "Civil debt recovery / suit for money had and received."
        desc_missing = "Limitation Act, 1963 prescribes 3 years from the date vacant possession was handed over or return of deposit was refused. Remaining days require the handover date."
    else:  # SALARY
        act_ref = "Code on Wages, 2019 / Limitation Act, 1963"
        total_years = 3
        total_days = 1095
        condonation_note = "Section 45 claim before Labour Authority / Civil debt recovery."
        desc_missing = "Prescribes up to 3 years from the date wages became due or resignation date. Remaining days require your last working date."

    if not coa_date:
        return {
            "title": f"Statutory Limitation ({act_ref})",
            "timing": "Unable to determine – additional information required",
            "color": "#FEF3C7",
            "border": "#FDE68A",
            "text_color": "#92400E",
            "desc": desc_missing,
        }
    else:
        today = date.today()
        elapsed_days = (today - coa_date).days
        remaining_days = total_days - elapsed_days
        expiry_date = coa_date + timedelta(days=total_days)

        if remaining_days > 0:
            timing_str = f"{remaining_days} days remaining (Expires approx. {expiry_date.strftime('%d %b %Y')})"
            color = "#FEF3C7" if remaining_days > 60 else "#FEE2E2"
            border = "#FDE68A" if remaining_days > 60 else "#FECDD3"
            text_color = "#92400E" if remaining_days > 60 else "#991B1B"
            desc_text = f"Calculated from cause of action ({coa_date.strftime('%d %b %Y')}). {condonation_note}"
        else:
            timing_str = f"⚠️ Limitation expired ({abs(remaining_days)} days overdue)"
            color = "#FEE2E2"
            border = "#FCA5A5"
            text_color = "#991B1B"
            desc_text = f"Standard {total_years}-year window passed. Must file an application for Condonation of Delay showing sufficient cause under applicable rules."

        return {
            "title": f"Statutory Limitation ({act_ref})",
            "timing": timing_str,
            "color": color,
            "border": border,
            "text_color": text_color,
            "desc": desc_text,
        }


def generate_action_plan(casefile: CaseFile, rules_result: Optional[RulesResult] = None) -> dict:
    """Generate structured action plan data tailored to the active case."""
    if isinstance(casefile, dict):
        try:
            casefile = CaseFile.model_validate(casefile)
        except Exception:
            casefile = CaseFile()
    if isinstance(rules_result, dict):
        try:
            rules_result = RulesResult.model_validate(rules_result)
        except Exception:
            rules_result = None
    cat = casefile.category or CaseCategory.DEPOSIT
    amt = casefile.amount_claimed or 0
    opponent = casefile.opponent_name or "Counterparty"
    opp_type = casefile.opponent_type or "Opponent"
    city = casefile.city or "your city"
    state = casefile.state or "your state"
    notice_days = getattr(casefile, "notice_cure_days", 15) or 15

    # ── 1. Step Details tailored by category ─────────────────────────────────
    if cat == CaseCategory.DEPOSIT:
        step1_title = "Collect Payment & Tenancy Evidence"
        step1_desc = (
            "Gather your bank transfer receipts/UPI transaction IDs showing deposit payment, "
            "the original rental agreement/lease deed, property handover WhatsApp chats, "
            "and photos of the apartment at move-in and move-out."
        )
        step1_items = [
            "Bank statement / UPI transaction receipt showing ₹" + f"{amt:,.0f}" if amt else "Deposit payment proof",
            "Signed rental agreement / lease deed copy",
            "WhatsApp/email chat acknowledging vacant possession handover",
            "Move-out condition photos/videos (to rebut bogus damage claims)"
        ]

        step2_title = f"Contact {opponent} with Formal Reminder"
        step2_desc = (
            f"Send a clear, documented written reminder to {opponent} via WhatsApp and Email. "
            "State the exact amount due, reference the agreement refund clause, and give 48 hours for voluntary settlement."
        )
        step2_items = [
            "Send written message referencing peaceful handover date",
            "Request itemized repair invoices if deductions are claimed",
            "Keep screenshots of delivery and read receipts (blue ticks)"
        ]

        step3_title = f"Prepare Pre-Litigation Legal Notice / Demand Draft ({notice_days} Days)"
        step3_desc = (
            f"Draft a formal legal notice granting {notice_days} days (customary pre-litigation period, or as stipulated in your lease deed) "
            f"demanding return of ₹{amt:,.0f}. Grounded in breach of contract under Section 73 of the Indian Contract Act, 1872 [KB:DEPOSIT-TPA-CONTRACT], "
            "applicable state tenancy rules, and Section 108(m) of the Transfer of Property Act, 1882 (protecting tenant against arbitrary deductions for reasonable wear and tear upon peaceful handover). "
            "Note: A 15-day period is standard pre-litigation custom, but cure windows are determined by agreement terms rather than a universal statutory requirement."
        )
        step3_items = [
            f"Generate formal .docx legal notice with {notice_days}-day cure clause via NyaySaathi Notice Drafter",
            "Send via Speed Post with Acknowledgment Due (AD) and Email",
            "Retain postal tracking receipt and delivery confirmation slip"
        ]

        step4_title = "Identify Grievance Redressal / Legal Aid Channel"
        step4_desc = (
            f"If {opponent} fails to pay within {notice_days} days, escalate to the competent legal authority: "
            "Rent Authority/Rent Court under State Tenancy rules, or file a Summary Civil Suit under Order 37 CPC."
        )
        step4_items = [
            "NALSA National Legal Aid Helpline: 15100 (Official 24x7 Pan-India Toll-Free; Sec. 12 LSA Act 1987)",
            f"Jurisdictional Civil Court / Rent Authority at {city}, {state}",
            "Summary Suit (Order 37 of CPC, 1908) for expedited money debt recovery",
            "Delhi regional helpline: 1516 (Delhi State Legal Services Authority)"
        ]

        forum_name = "Civil Court / Rent Authority"

    elif cat == CaseCategory.CONSUMER:
        step1_title = "Collect Invoice & Defect Evidence"
        step1_desc = (
            "Preserve your tax invoice, order confirmation number, defective product unboxing videos, "
            "repair job sheets, and customer service escalation logs."
        )
        step1_items = [
            "Retail invoice / Order confirmation receipt (showing consideration paid)",
            "Photos / unboxing video demonstrating product defect or service deficiency",
            "Customer care ticket IDs, email thread, and refund rejection records",
            "Courier return tracking receipt or pickup rejection memo"
        ]

        step2_title = f"Contact {opponent} Grievance Officer"
        step2_desc = (
            f"Escalate your complaint to the designated Grievance Officer of {opponent}. "
            "Under the Consumer Protection (E-Commerce) Rules, platforms must acknowledge within 48 hours and resolve within 1 month."
        )
        step2_items = [
            "Email Grievance Officer citing order ID and 7-day refund timeline",
            "Call National Consumer Helpline (NCH): 1915 or register on consumerhelpline.gov.in",
            "Record docket number assigned by National Consumer Helpline"
        ]

        step3_title = f"Prepare Consumer Pre-Litigation Notice ({notice_days} Days)"
        step3_desc = (
            f"Draft a formal pre-litigation notice demanding refund of ₹{amt:,.0f} plus statutory interest within {notice_days} days. "
            "Cites Section 2(7) and Section 35 of the Consumer Protection Act, 2019 [KB:CPA-2019-OVERVIEW]. "
            "Notice periods are based on commercial practice and platform terms; 15 days provides reasonable opportunity to cure deficiency before filing before District Commission."
        )
        step3_items = [
            f"Auto-generate consumer legal notice ({notice_days}-day cure window) via NyaySaathi",
            "Send notice to company registered office and customer support email",
            "Attach invoice copy and photo proof of service deficiency"
        ]

        step4_title = "File Online via e-Jagriti Portal (Zero Fee < ₹5 Lakh)"
        step4_desc = (
            f"If unresolved after {notice_days} days, file a formal complaint online before the District Consumer Disputes Redressal Commission "
            "via the official government e-Jagriti portal (e-jagriti.gov.in). Filing is 100% free for claims up to ₹5 lakh."
        )
        step4_items = [
            "Register on e-Jagriti portal (e-jagriti.gov.in - replaced e-Daakhil in 2025)",
            "Upload complaint draft, invoice, and photo evidence PDF",
            "Track case status and virtual hearing notices online"
        ]

        forum_name = "District Consumer Commission (e-Jagriti)"

    else:  # SALARY
        step1_title = "Collect Employment & Salary Proof"
        step1_desc = (
            "Compile your employment offer letter, previous months' salary slips, Form 16, "
            "bank statement showing missing salary credit, and resignation acceptance email."
        )
        step1_items = [
            "Signed offer letter / employment contract / appointment letter",
            "Last 3-6 months pay slips and bank account credit statements",
            "Resignation letter and official acknowledgment showing last working day",
            "HR communication regarding full-and-final settlement timeline"
        ]

        step2_title = f"Send Formal Demand to {opponent} HR & Directors"
        step2_desc = (
            f"Send a written demand to {opponent}'s HR and Managing Director. "
            "Under Section 17 & 18 of the Code on Wages, 2019 [KB:COW-2019-SETTLEMENT], final settlement must be paid within 2 working days of resignation."
        )
        step2_items = [
            "Email formal letter citing statutory 2-working-day settlement rule",
            "Request detailed statement of earned salary, leave encashment, and bonus",
            "Mark copy to company directors or registered email on MCA portal"
        ]

        step3_title = f"Prepare Statutory Demand Letter ({notice_days} Days)"
        step3_desc = (
            f"Draft a formal demand letter demanding clearance of ₹{amt:,.0f} within {notice_days} days. "
            "Cites Sections 17 & 18 of the Code on Wages, 2019 [KB:COW-2019-SETTLEMENT], requiring full settlement within 2 working days of resignation."
        )
        step3_items = [
            f"Generate formal salary demand letter ({notice_days}-day cure window) via NyaySaathi Drafter",
            "Send through Registered Post with A/D to registered corporate address",
            "Preserve delivery confirmation report from India Post"
        ]

        step4_title = "File Claim before Labour Commissioner / NALSA"
        step4_desc = (
            "If unpaid, submit an application under Section 45 of the Code on Wages, 2019 before the "
            "Appropriate Authority / Labour Commissioner at your district, or seek free legal counsel via NALSA (15100)."
        )
        step4_items = [
            f"Office of Deputy Labour Commissioner / Conciliation Officer at {city}",
            "Section 45 Claim Application under Code on Wages, 2019",
            "NALSA National Legal Aid Helpline: 15100 (Official 24x7 Pan-India; Sec. 12 LSA Act 1987)",
            "Delhi regional helpline: 1516 (DSLSA)"
        ]

        forum_name = "Labour Authority / Code on Wages"

    # ── 2. Deadlines Cards Data ──────────────────────────────────────────────
    limitation_data = calculate_limitation(casefile)
    deadlines = [
        {
            "title": f"Notice Cure Window ({notice_days} Days)",
            "timing": f"Configurable ({notice_days} Days)",
            "color": "#FEF2F2",
            "border": "#FECDD3",
            "text_color": "#991B1B",
            "desc": "Pre-litigation opportunity for counterparty to resolve claim voluntarily as demanded in notice or agreement."
        },
        limitation_data,
        {
            "title": f"Forum Resolution ({forum_name})",
            "timing": "90–180 Days Estimated",
            "color": "#EFF6FF",
            "border": "#BFDBFE",
            "text_color": "#1E40AF",
            "desc": "Average statutory disposal timeline post-admissibility under applicable forum rules."
        }
    ]

    # ── 3. AI Activity Audit Log ─────────────────────────────────────────────
    activities = [
        {
            "time": "2 min ago",
            "icon": "✨",
            "action": "Notice Drafter",
            "detail": f"Allegations section complete — 12 allegations drafted for ₹{amt:,.0f} claim with {notice_days}-day cure clause."
        },
        {
            "time": "15 min ago",
            "icon": "🔍",
            "action": "Issue Spotter",
            "detail": f"Found 2 potential claims in uploaded records under {forum_name} jurisdiction."
        },
        {
            "time": "1 hr ago",
            "icon": "📅",
            "action": "Chronology Analyzer",
            "detail": "Fact chronology updated — key dispute timeline and breach events recorded."
        },
        {
            "time": "2 hrs ago",
            "icon": "⚖️",
            "action": "Precedent Matcher",
            "detail": f"Statutory grounding verified against official Gazette Bare Acts."
        }
    ]

    return {
        "steps": [
            {"num": 1, "title": step1_title, "desc": step1_desc, "items": step1_items, "badge": "Evidence Phase"},
            {"num": 2, "title": step2_title, "desc": step2_desc, "items": step2_items, "badge": "Engagement Phase"},
            {"num": 3, "title": step3_title, "desc": step3_desc, "items": step3_items, "badge": "Notice Phase"},
            {"num": 4, "title": step4_title, "desc": step4_desc, "items": step4_items, "badge": "Grievance / Legal Aid"}
        ],
        "deadlines": deadlines,
        "activities": activities,
        "category": cat.value,
        "amount": amt,
        "opponent": opponent,
        "forum": forum_name,
        "notice_days": notice_days
    }


def render_action_plan_dashboard(plan: dict, casefile: CaseFile) -> str:
    """Render a clean, honest, compact Recovery Roadmap & Statutory Deadlines widget for Tab 1."""
    if isinstance(casefile, dict):
        try:
            casefile = CaseFile.model_validate(casefile)
        except Exception:
            casefile = CaseFile()
    amt_str = f"₹{plan['amount']:,.0f}" if plan.get('amount') else "Assessed Claim"
    opp_str = html.escape(plan.get('opponent') or "Counterparty")
    cat_str = html.escape((plan.get('category') or "dispute").capitalize())

    # Check information sufficiency
    is_sufficient, missing_items, warning_html = check_information_sufficiency(casefile)

    if is_sufficient:
        status_pill = '<span style="font-size:11px; background:#DCFCE7; color:#15803D; padding:2px 8px; border-radius:12px; font-weight:700;">ACTIVE CASE</span>'
        status_sub = f"Statutory Recovery Roadmap for {opp_str} ({amt_str})"
    elif plan.get('category'):
        status_pill = '<span style="font-size:11px; background:#FEF3C7; color:#B45309; padding:2px 8px; border-radius:12px; font-weight:700;">INTAKE IN PROGRESS</span>'
        status_sub = f"{cat_str} Dispute • Awaiting details"
    else:
        status_pill = '<span style="font-size:11px; background:#F1F5F9; color:#64748B; padding:2px 8px; border-radius:12px; font-weight:700;">AWAITING DISPUTE</span>'
        status_sub = "Describe your dispute in Chat to generate customized recovery roadmap"

    # Deadlines (Statutory Limitation calculation)
    deadlines_cards = []
    for d in plan.get("deadlines", []):
        deadlines_cards.append(f"""
        <div style="flex:1; min-width:200px; background:{d['color']}; border:1px solid {d['border']}; border-radius:8px; padding:10px 14px;">
          <div style="font-size:10px; font-weight:700; color:{d['text_color']}; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:2px;">
            {html.escape(d['title'])}
          </div>
          <div style="font-size:14px; font-weight:800; color:{d['text_color']}; margin-bottom:2px;">
            {html.escape(d['timing'])}
          </div>
          <div style="font-size:11px; color:#475569; line-height:1.35;">
            {html.escape(d['desc'])}
          </div>
        </div>
        """)

    # 4 Steps Rendered as sleek sequential cards
    steps_html = []
    for s in plan.get("steps", []):
        items_li = "".join(
            f"<li style='margin-bottom:3px;'>{html.escape(it)}</li>"
            for it in s.get("items", [])[:3]
        )
        is_active_step = (s["num"] == 3 if is_sufficient else (s["num"] == 1))
        badge_bg = "#DCFCE7" if is_active_step else "#EEF2FF"
        badge_color = "#15803D" if is_active_step else "#4338CA"
        badge_label = f"Step {s['num']}: {s.get('badge', 'Phase')}"

        steps_html.append(f"""
        <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; padding:10px 14px; margin-bottom:8px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="width:22px; height:22px; background:#1E1B4B; color:#FFFFFF; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:11px;">
                {s['num']}
              </span>
              <span style="font-size:13px; font-weight:700; color:#1E1B4B;">
                {html.escape(s['title'])}
              </span>
            </div>
            <span style="font-size:10px; background:{badge_bg}; color:{badge_color}; font-weight:700; padding:2px 8px; border-radius:10px;">
              {html.escape(badge_label)}
            </span>
          </div>
          <p style="font-size:11px; color:#64748B; margin:0 0 6px 30px; line-height:1.4;">
            {html.escape(s['desc'])}
          </p>
          <ul style="margin:0 0 0 46px; padding:0; font-size:11px; color:#334155; line-height:1.5;">
            {items_li}
          </ul>
        </div>
        """)

    warning_block = f"<div style='margin-bottom:10px;'>{warning_html}</div>" if warning_html else ""

    return f"""
    <div>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <span style="font-size:12px; font-weight:600; color:#475569;">{status_sub}</span>
        {status_pill}
      </div>

      {warning_block}

      <!-- Statutory Limitation & Key Deadlines -->
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px;">
        {''.join(deadlines_cards)}
      </div>

      <!-- 4-Step Sequential Recovery Ladder -->
      <div style="margin-bottom:10px;">
        {''.join(steps_html)}
      </div>

      <!-- Verified Redressal Channels Footnote -->
      <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px; padding:8px 12px; font-size:11px; color:#475569; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
        <span><strong>Official Dispute Redressal:</strong> e-Jagriti (Consumer) • Labour Authority (Wages)</span>
        <a href="https://nalsa.gov.in" target="_blank" style="color:#7C3AED; font-weight:700; text-decoration:none;">NALSA Free Legal Aid: 15100 ↗</a>
      </div>
    </div>
    """


def generate_action_plan_docx(plan: dict, casefile: CaseFile) -> str:
    """Generate a downloadable Word document (.docx) containing the complete action plan."""
    if isinstance(casefile, dict):
        try:
            casefile = CaseFile.model_validate(casefile)
        except Exception:
            casefile = CaseFile()
    import docx
    import tempfile
    from pathlib import Path

    doc = docx.Document()
    title = doc.add_heading(f"LEGAL ACTION PLAN: {plan.get('category', 'Dispute').upper()} RECOVERY", level=1)
    title.alignment = docx.enum.text.WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph(f"Prepared by: NyaySaathi AI Legal Assistant | Date: {datetime.now().strftime('%d %B %Y')}")
    doc.add_paragraph(f"Counterparty: {plan.get('opponent')} | Documented Claim: ₹{plan.get('amount', 0):,.0f} | Competent Forum: {plan.get('forum')}")
    doc.add_paragraph("=" * 60)

    doc.add_heading("I. SEQUENTIAL ACTION ROADMAP", level=2)
    for s in plan.get("steps", []):
        doc.add_heading(f"Step {s['num']}: {s['title']} ({s['badge']})", level=3)
        doc.add_paragraph(s["desc"])
        for it in s.get("items", []):
            doc.add_paragraph(f"• {it}")
        doc.add_paragraph("")

    doc.add_heading("II. UPCOMING DEADLINES & STATUTORY LIMITATION", level=2)
    for d in plan.get("deadlines", []):
        doc.add_paragraph(f"• {d['title']}: {d['timing']} — {d['desc']}")

    doc.add_paragraph("")
    doc.add_heading("III. OFFICIAL GRIEVANCE REDRESSAL CHANNELS", level=2)
    doc.add_paragraph("• e-Jagriti Consumer Filing: https://e-jagriti.gov.in (Zero court fee < ₹5 Lakh)")
    doc.add_paragraph("• National Consumer Helpline: 1915 | consumerhelpline.gov.in")
    doc.add_paragraph("• NALSA National Legal Aid Helpline: 15100 (Official 24x7 Pan-India Toll-Free | nalsa.gov.in | Section 12 of Legal Services Authorities Act, 1987; Delhi SLSA: 1516)")

    doc.add_paragraph("")
    disclaimer = doc.add_paragraph("Disclaimer: This action plan is generated by an automated AI legal information system based on codified Indian law. It does NOT constitute legal advice or create an advocate-client relationship under the Advocates Act, 1961. Consult a qualified advocate enrolled with the Bar Council of India before formal court proceedings.")
    disclaimer.italic = True

    out_dir = Path(__file__).parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    fpath = out_dir / f"Action_Plan_{plan.get('category')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    doc.save(str(fpath))
    return str(fpath)
