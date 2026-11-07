"""Pydantic schemas for Paisa Wapas — CaseFile, Advice, Draft, KBEntry."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class CaseCategory(str, Enum):
    DEPOSIT = "deposit"
    CONSUMER = "consumer"
    SALARY = "salary"
    OUT_OF_SCOPE = "out_of_scope"


class DocType(str, Enum):
    LEGAL_NOTICE = "legal_notice"
    CONSUMER_COMPLAINT = "consumer_complaint"
    SALARY_DEMAND = "salary_demand_letter"


class Forum(str, Enum):
    CONSUMER_COMMISSION = "District Consumer Disputes Redressal Commission"
    LABOUR_AUTHORITY = "Labour Commissioner / Appropriate Authority under Code on Wages"
    CIVIL_COURT = "Civil Court"
    NALSA = "Free Legal Aid (NALSA 15100)"
    OUT_OF_SCOPE = "Refer to a lawyer"


# ── CaseFile ─────────────────────────────────────────────────────────────────

class CaseFile(BaseModel):
    """Structured intake of a user's money dispute."""

    category: Optional[CaseCategory] = Field(
        None, description="Type of dispute: deposit | consumer | salary"
    )
    user_name: Optional[str] = Field(None, description="Name of the person seeking help")
    opponent_name: Optional[str] = Field(
        None, description="Name of the landlord / company / employer"
    )
    opponent_type: Optional[str] = Field(
        None, description="e.g. landlord, e-commerce company, employer, airline"
    )
    amount_claimed: Optional[float] = Field(
        None, description="Amount in ₹ the user says they are owed"
    )
    currency: str = Field("INR", description="Always INR for this app")
    state: Optional[str] = Field(
        None, description="Indian state where the user is located or incident happened"
    )
    city: Optional[str] = Field(None, description="City")
    key_dates: Optional[dict[str, str]] = Field(
        None,
        description="Relevant dates, e.g. {'deposit_paid': '2024-06-15', 'vacated': '2025-01-10'}",
    )
    dates_approximate: bool = Field(
        False, description="True if dates were inferred from relative expressions"
    )
    proof_available: Optional[list[str]] = Field(
        None,
        description="Evidence the user has: receipts, screenshots, emails, offer letter, etc.",
    )
    what_tried: Optional[str] = Field(
        None, description="What the user has already tried: called, emailed, nothing, etc."
    )
    story_summary: Optional[str] = Field(
        None, description="Free-text summary of the situation in 2–3 sentences"
    )
    escalation_flag: Optional[str] = Field(
        None,
        description="Non-null means this case must be routed to a human (reason stored here)",
    )
    user_language: str = Field(
        "English", description="Detected language/script of the user"
    )
    notice_cure_days: int = Field(
        15, description="Configurable notice cure period in days (e.g., 7, 15, 30 days based on agreement or custom)"
    )
    cause_of_action_date: Optional[date] = Field(
        None, description="Date when cause of action arose (vacating date, defective delivery date, wage due date)"
    )
    is_demo: bool = Field(
        False, description="Flag indicating if this is an illustrative demo/sample case"
    )


# ── Intake LLM output ───────────────────────────────────────────────────────

class IntakeResponse(BaseModel):
    casefile: CaseFile
    next_questions: list[str] = Field(default_factory=list)
    next_question_or_clarification: Optional[str] = Field(
        None, description="Optional single clarification question or summary"
    )
    escalation_flag: Optional[str] = None


# ── Rules engine output ─────────────────────────────────────────────────────

class RulesResult(BaseModel):
    forum: Optional[Forum] = None
    doc_type: Optional[DocType] = None
    limitation_estimate: Optional[str] = Field(
        None, description="Human-readable limitation period estimate with arithmetic"
    )
    limitation_warning: bool = Field(
        False, description="True if limitation is close or possibly expired"
    )
    missing_proof: list[str] = Field(
        default_factory=list, description="Proof items that would strengthen the case"
    )
    escalation: Optional[str] = Field(
        None, description="Reason to route to a human, if any"
    )
    amount_in_range: bool = Field(
        True, description="True if amount ≤ ₹50 lakh for consumer forum"
    )


# ── KB entry ─────────────────────────────────────────────────────────────────

class KBEntry(BaseModel):
    id: str
    category: list[str]
    act: str
    section: str
    plain_summary: str
    applies_when: str
    source_url: str
    verified: bool = False
    last_checked: Optional[str] = None
    notes: Optional[str] = None


# ── Validator output ─────────────────────────────────────────────────────────

class ValidatorHit(BaseModel):
    original_text: str
    matched_pattern: str
    action: str  # "removed", "replaced", "blocked_regenerate"
    kb_id_found: Optional[str] = None


# ── Feature 2: Evidence and Document Analysis ─────────────────────────────────

class ClauseHighlight(BaseModel):
    clause_title: str = Field(..., description="e.g. Document Dates / Signature Blocks, Deduction Clause")
    text_snippet: str = Field(..., description="Excerpt from the document")
    severity: str = Field("medium", description="high | medium | low")
    issue_description: str = Field(..., description="Why this clause is problematic or notable")


class DocumentAnalysisResult(BaseModel):
    document_type: str = Field(..., description="Rental Agreement, Payment Receipt, Invoice, Employment Contract, etc.")
    dispute_category: str = Field("deposit", description="deposit | consumer | salary | out_of_scope")
    overall_risk_score: int = Field(50, description="0 to 100, where 100 is highest risk / weakness")
    risk_level: str = Field("Medium", description="Low | Medium | High")
    who_does_this_favor: str = Field("Balanced", description="Favors Counterparty | Slightly favors counterparty | Balanced | Favors You")
    favor_score: int = Field(0, description="-100 (counterparty) to +100 (you)")
    clause_counts: dict[str, int] = Field(default_factory=lambda: {"high": 0, "medium": 0, "low": 0})
    extracted_parties: dict[str, str] = Field(default_factory=dict, description="{'landlord': '...', 'tenant': '...'}")
    extracted_amount: Optional[float] = None
    extracted_dates: dict[str, str] = Field(default_factory=dict)
    key_clauses: list[ClauseHighlight] = Field(default_factory=list)
    top_issues: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    summary_markdown: str = ""
    review_markdown: str = ""


# ── Feature 4 Standing Additions: Dynamic Facts, RAG & Discrepancy Verification ──

class MissingFactItem(BaseModel):
    key: str = Field(..., description="Machine key, e.g. vacate_date, written_agreement")
    question: str = Field(..., description="Targeted follow-up question for user")
    legal_relevance: str = Field(..., description="Why this fact matters under Indian law")
    is_critical: bool = True


class DiscrepancyItem(BaseModel):
    field: str = Field(..., description="e.g. Claimed Amount, Landlord Name, Notice Period")
    discrepancy_type: str = Field("amount_mismatch", description="amount_mismatch | party_mismatch | date_conflict | notice_clause_conflict")
    user_statement: str = Field(..., description="What the user stated in chat")
    document_evidence: str = Field(..., description="What the uploaded document reflects")
    severity: str = Field("high", description="high | medium | low")
    explanation: str = Field(..., description="Legal implication of discrepancy")
    recommended_action: str = Field(..., description="Suggested resolution before notice issue")


class EvidenceVerificationReport(BaseModel):
    has_discrepancies: bool = False
    discrepancy_count: int = 0
    items: list[DiscrepancyItem] = Field(default_factory=list)
    verified_matches: list[str] = Field(default_factory=list)
    summary: str = ""


class RAGResultItem(BaseModel):
    id: str
    act_name: str
    section: str
    title: str
    source_url: str
    relevance_score: float = 0.9
    relevance_label: str = "High Match"
    statutory_summary: str
    practical_guidance: str
    official_citation: str

