# AI Quality Evaluation Benchmark Report

**Evaluation Timestamp:** 2026-11-08T04:26:49.469787  
**Overall Benchmark Accuracy:** **100.0%** (20/20 cases fully passed)

---

### Quality Dimension Performance Matrix

| Evaluation Dimension | Description | Accuracy |
|----------------------|-------------|:--------:|
| **1. Category Identification** | Correctly maps query to `deposit`, `consumer`, `salary`, or `out_of_scope` | **100.0%** |
| **2. Legal Provisions Retrieval** | Retrieves applicable Indian statutes (CPA 2019, Code on Wages, Contract Act, TPA) | **100.0%** |
| **3. Zero Hallucinated Sections** | Completely avoids repealed acts (Payment of Wages 1936) & fake citations | **100.0%** |
| **4. Missing Information Recognition**| Detects missing dates, amounts, agreements, and generates follow-up queries | **100.0%** |
| **5. Appropriate Next Steps** | Produces actionable 4-step recovery plan (Evidence → Contact → Notice → Forum) | **100.0%** |

---

### Case-by-Case Benchmark Results (20 Legal Situations)

| Case ID | Legal Situation | Category | Provisions | No Fake | Missing Info | Next Steps | Result |
|:-------:|-----------------|:--------:|:----------:|:-------:|:------------:|:----------:|:------:|
| TC01 | Bangalore Rental Deposit (Agreement + Re | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC02 | Delhi Tenancy Deposit (Unwritten Lease,  | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC03 | Pune Rental Deposit (Wear & Tear Deducti | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC04 | Flipkart Cracked Phone Refund (Hindi) | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC05 | Cancelled Airline Ticket Refund (18 Mont | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC06 | Coaching Institute Fee Refund (Tamil / E | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC07 | Startup Unpaid Wages (Mumbai, Offer Lett | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC08 | MNC Full & Final Settlement Withheld (Ma | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC09 | Repealed Law Trap (Payment of Wages Act  | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC10 | Fabricated Case Citation Trap (Supreme C | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC11 | Criminal Intimidation & Lockout (Escalat | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC12 | High Value Builder Refund (> ₹50 Lakh Pe | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC13 | Matrimonial Maintenance (Out of Scope) | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC14 | Cyber Phishing / OTP Scam (Criminal Out  | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC15 | Incomplete Fact Scenario: Rental Deposit | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC16 | Incomplete Fact Scenario: E-Commerce (Mi | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC17 | Incomplete Fact Scenario: Unpaid Salary  | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC18 | Evidence Discrepancy Case (Claim ₹30k vs | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC19 | Vehicle Authorized Service Deficiency | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |
| TC20 | Commercial Complex Lease Deposit Withhel | ✓ | ✓ | ✓ | ✓ | ✓ | **PASS** |

---
*Report generated automatically by Paisa Wapas AI Quality Evaluation Engine.*
