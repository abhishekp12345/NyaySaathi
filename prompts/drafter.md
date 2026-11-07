Draft a {doc_type} (legal_notice | consumer_complaint | salary_demand_letter) in formal Indian English,
using ONLY facts from the CASEFILE and law from the KNOWLEDGE BASE (cite as [KB:ID] in a separate
"Sources" list at the end, not inside the formal text unless the reference is verified).

- Every missing fact → [[PLACEHOLDER: what's needed]]. Never invent names, addresses, dates, amounts,
  order IDs or account numbers.
- Demand a specific amount and a clear deadline (use notice_cure_days from casefile or default 15 days; note that notice cure periods are contractual or customary pre-litigation practice, not a universal statutory mandate).
- For tenancy deposit disputes, base the claim on breach of contract under Section 73 of the Indian Contract Act, 1872 and Section 108(m) of the Transfer of Property Act, 1882 (prohibiting arbitrary deductions for reasonable wear and tear upon peaceful handover). Do not treat Section 108 as a standalone deposit refund guarantee.
- State the next step the sender will take if unpaid, matching the forum in RULES ENGINE RESULT.
- Keep it under one page. No threats beyond lawful next steps. No interest rate unless the user gave one.
- After the draft, write 3–5 bullet "Before you send" checks in {user_language}
  (how to send — e.g. registered post / email, keep proof of delivery, attach copies not originals).

CASEFILE: {casefile_json}
RULES ENGINE RESULT: {rules_json}
KNOWLEDGE BASE: {kb_entries_json}
