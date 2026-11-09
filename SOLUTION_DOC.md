# NyaySaathi (न्याय साथी) — AI Legal Assistant for Everyday Money Disputes in India
**Kuku AI Generalist Assignment — Problem 2 Submission Document (2 Pages)**  
**Candidate Name:** Abhishek Kumar Priyadershi | **Roll No:** 230047 | **Branch:** BSBE | **College:** IIT Kanpur | **Problem:** Problem 2 (AI Lawyer)  
**GitHub Repository:** https://github.com/abhishekp12345/NyaySaathi | **Prototype:** Gradio UI (Port 7860 / Cloud) | **Raw Outputs:** `outputs/`

---

### 1. Problem Choice, Scope & Safety Guardrails
* **The Problem:** In India, millions of ordinary people lose money in everyday disputes—landlords refusing to return rental deposits, shopping websites refusing refunds, or employers withholding final salaries. Hiring a lawyer costs ₹5,000 to ₹10,000 just to send a notice, which makes no sense for a ₹20,000 claim. Because of this, most people simply give up.
* **Our Scope (What We Solve):** Instead of trying to build an AI that answers every legal question in India, **NyaySaathi** focuses on one clear goal: **recovering money under ₹50 Lakh before going to court**. We handle three common disputes:
  1. *Rental Security Deposits:* Unfair deductions or withheld deposits (Transfer of Property Act, 1882 & Indian Contract Act, 1872).
  2. *Consumer Refunds:* Defective products, cancelled bookings, or bad service (Consumer Protection Act, 2019 & E-Commerce Rules, 2020).
  3. *Unpaid Salary:* Withheld monthly pay or delayed full-and-final settlement (Code on Wages, 2019).
* **Safety Guardrail (What We Refuse to Do):** NyaySaathi does not give advice on criminal matters, threats, physical violence, family or divorce disputes, or cases already in court. When a user mentions threats or violence, the AI stops giving advice immediately and shares official helplines:
  - **Police Emergency:** 112 (with advice to register an FIR).
  - **Free Legal Aid (NALSA):** 15100 (toll-free government legal support).
  - **National Consumer Helpline:** 1915.

---

### 2. How the System Works: AI vs Pure Code
We do not use a single AI prompt for everything, because language models can make up fake laws. Instead, we divide the work between generative AI and reliable Python code:

```
User (Text or Voice) ──▶ AI Intake (Understands Hindi/English) ──▶ Rules Engine (Pure Code)
                                                                            │
User Downloads Notice (.docx) ◀── Citation Checker (Code) ◀── AI Notice Drafter ◀──┘
```

* **What the AI Handles (Language & Conversation):**
  - *Voice & Text Intake:* Listens to voice notes or text in Hindi, English, and Hinglish. It pulls out key facts (who owes money, how much, and what happened).
  - *Simple Legal Advice:* Explains the user's legal rights in plain, everyday language using 5 simple sections.
  - *Drafting the Demand Letter:* Writes a polite and formal legal notice in English, leaving any missing details as clear `[[PLACEHOLDER]]` markers.
  - *Practice Chat:* Plays the role of the landlord or company in a 4-round practice chat so the user can build confidence before negotiating.
* **What Pure Code Handles (Zero Hallucination Guardrails):**
  - *Limitation Deadline Clock (`action_plan.py`):* Uses simple math in Python to count remaining days before the legal deadline expires (e.g. 2 years under Section 69 of the Consumer Protection Act).
  - *Verified Bare Acts Database (`kb/law_kb.yaml`):* Contains verified sections from India Code. The AI can only cite laws from this verified list.
  - *Old Law Blocker (`validator.py`):* Scans the AI's output and blocks repealed laws (such as the old *Payment of Wages Act 1936* or *IPC*), replacing them with new laws (*Code on Wages 2019* and *BNS 2023*).
  - *Proof Checker (`rules.py`):* Checks if bank transfer receipts match the claimed amount and flags any difference.
* **Cost & Economics:**
  - One complete case takes about 5,000 tokens across all steps.
  - Using fast models like Groq Qwen 2.5 or Gemini Flash, each case costs about **₹0.13 (13 paise)**.
  - Helping 10,000 citizens every day costs less than **₹1,250 per day**, making free access easily affordable.

---

### 3. Testing, Results & Honest Failures
* **20-Case Automated Test Benchmark:**
  We tested NyaySaathi on 20 realistic situations (messy voice notes, regional dialects, trick questions, and criminal threats):
  - *Dispute Identification:* **100% (20/20)**
  - *Correct Law Selection:* **100% (20/20)**
  - *Zero Fake or Repealed Citations:* **100% (20/20 — 0 hallucinations)**
  - *Recognizing Missing Information:* **100% (20/20)**
  - *Correct Emergency Escalation:* **100% (20/20)**
* **Real Mistakes the AI Made and How We Fixed Them:**
  - *Mistake 1: Quoting Repealed Laws.* Early on, the AI repeatedly quoted the *Payment of Wages Act 1936* and *Indian Evidence Act 1872*. Both laws have been replaced by the *Code on Wages 2019* and *Bharatiya Sakshya Adhiniyam 2023*. We fixed this by adding a code-level validator that blocks repealed laws before they reach the user.
  - *Mistake 2: Missing Details in User Messages.* When users did not mention the exact amount or order date, the AI used to show an error. We fixed this by adding follow-up clarification questions in simple Hindi and English.
  - *Mistake 3: State Differences in Rental Rules.* Tenancy rules vary by state (for example, Maharashtra vs Karnataka). The system now asks for the user's city and state before giving rental advice.

---

### 4. What Is Delivered in the Project
1. **Interactive Prototype:** Live at https://d70ff15dcd2ab9e3a3.gradio.live (and GitHub at https://github.com/abhishekp12345/NyaySaathi) with microphone voice input and `.docx` downloads.
2. **Pre-Litigation Documents:** Generates both a formal Legal Notice and a 4-step Recovery Roadmap with customizable cure periods (7, 15, or 30 days).
3. **Raw Evaluation Files:** Complete unedited test results saved in `outputs/evaluation_report.json` and `validator_log.jsonl`.
4. **Legal Disclaimer:** Clearly informs users that the tool provides legal information, not formal advocate representation under the Advocates Act, 1961.
