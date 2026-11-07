# ⚖️ NyaySaathi (न्याय साथी) — AI Legal Assistant for Everyday Money Disputes in India

**NyaySaathi (न्याय साथी)** is a conversational AI prototype that helps ordinary people in India navigate everyday money disputes — specifically security deposits not returned, consumer refunds not given, and unpaid salaries. It understands text and voice input in multiple Indian languages, explains your legal options in plain words, and drafts a legal notice or complaint you can download and send.

> **What it is NOT:** This is not a lawyer. It does not provide legal advice. It will tell you when you need a real lawyer and give you the right helpline numbers.

---

## 🎯 Scope

### ✅ Covered
| Sub-type | Example | Remedy path |
|----------|---------|-------------|
| **Security deposit** | Landlord won't return deposit | Legal notice → Civil court |
| **Consumer refund** | E-commerce, airline, telecom, coaching centre | NCH 1915 → e-Jagriti complaint → Consumer Commission |
| **Unpaid salary** | Private employer withholds wages/F&F | Demand letter → Labour Commissioner |

### ❌ NOT Covered (auto-detected and routed to a human)
- Criminal matters (FIR, threats, harassment, fraud)
- Family / matrimonial / divorce
- Property title disputes or eviction defence
- Government employee service matters
- Cases already in court
- Claims above ₹50 lakh
- Expired limitation periods (flagged with warning)
- Violence or danger → emergency numbers given

---

## 🚀 Quick Start

### Local
```bash
cd paisa-wapas
pip install -r requirements.txt

# Set your API key (pick one)
export GEMINI_API_KEY=your_key_here
# OR
export OPENAI_API_KEY=your_key_here

# Optional: change the model
export LLM_MODEL=gemini/gemini-2.0-flash   # default

python app.py
# → Open http://localhost:7860
```

### Hugging Face Spaces
1. Create a new Gradio Space on [huggingface.co/spaces](https://huggingface.co/spaces)
2. Upload the `paisa-wapas/` folder
3. Set `GEMINI_API_KEY` (or other API key) as a Space Secret
4. The app auto-starts on `app.py`

### Swap Models (zero code changes)
```bash
LLM_MODEL=gemini/gemini-2.0-flash python app.py       # Google (free tier)
LLM_MODEL=openai/gpt-4o-mini python app.py             # OpenAI
LLM_MODEL=anthropic/claude-3-haiku python app.py        # Anthropic
LLM_MODEL=groq/llama-3.1-70b-versatile python app.py   # Groq
```

### Voice Input
- **Default:** Gemini processes audio natively (no separate STT step)
- **Optional:** Set `STT_PROVIDER=sarvam` and `SARVAM_API_KEY=...` for Sarvam AI (better for Indian languages)
- Transcript is always shown to the user for correction before proceeding

---

## 🏗️ Architecture

```
User (text/voice, any language)
       │
       ▼
  ┌─────────┐     ┌─────────────┐
  │ Intake   │────▶│ Rules Engine │ (code — no LLM)
  │ (LLM)   │     │  escalation  │
  └─────────┘     │  limitation  │
       │          │  forum pick  │
       ▼          │  proof check │
  ┌─────────┐     └──────┬──────┘
  │ Confirm │◀───────────┘
  │ (human) │
  └────┬────┘
       │ user says "yes"
       ▼
  ┌─────────┐     ┌───────────┐
  │ Advisor  │────▶│ Validator  │ (code — no LLM)
  │ (LLM)   │     │ citation ✓ │
  └─────────┘     │ repealed ✗ │
       │          └───────────┘
       ▼
  ┌─────────┐
  │ Drafter  │───▶ .docx download
  │ (LLM)   │
  └─────────┘
       │
       ▼ (optional)
  ┌──────────┐
  │ Practice │  role-play the confrontation
  │ (LLM)   │
  └──────────┘
```

### AI vs. Code Split
| Component | AI (LLM) | Code (deterministic) |
|-----------|----------|---------------------|
| Language detection | ✅ | |
| Intake (fact extraction) | ✅ | |
| Escalation check | | ✅ `rules.py` |
| Limitation calculation | | ✅ `rules.py` (arithmetic shown) |
| Forum selection | | ✅ `rules.py` |
| Missing proof checklist | | ✅ `rules.py` |
| Advice generation | ✅ (grounded in KB) | |
| Citation validation | | ✅ `validator.py` |
| Repealed-law blocking | | ✅ `validator.py` |
| Document drafting | ✅ (grounded in KB) | |
| .docx generation | | ✅ `python-docx` |

---

## 🛡️ How Hallucination Is Controlled

1. **Curated Knowledge Base** (`kb/law_kb.yaml`): 20 hand-checked entries covering statutes, forums, limitation periods, filing routes, and practical guidance. Every legal statement must cite a KB entry.

2. **Citation Rule**: The advisor and drafter prompts require `[KB:ID]` citations. The validator checks that every legal reference maps to a KB entry ID.

3. **Post-generation Validator** (`validator.py`):
   - Regex-scans for statute/section mentions
   - Strips unverified references → "(reference removed: could not verify)"
   - Blocks repealed laws (Payment of Wages Act, Minimum Wages Act, IPC, CrPC, Indian Evidence Act) — regenerates once, then strips
   - Logs every hit to `outputs/validator_log.jsonl`

4. **No Case Law**: The app never cites judgments. Prompts explicitly forbid it.

5. **Verified flag**: KB entries with `verified: false` produce hedged language only ("this may be covered by … — please confirm with a lawyer").

---

## 📋 Assumptions

- **Documents in English**: Legal notices and complaints are generated in English (standard for Indian legal forums), with plain-language explanation in the user's language
- **User's state is asked, not assumed**: Tenancy law is state-specific
- **₹50 lakh district limit**: Claims above this are routed to a lawyer
- **Limitation dates are estimates**: Shown with arithmetic, labeled as estimates, not guarantees
- **KB last checked**: 2026-11-06

---

## ⚠️ Known Limitations & Failure Modes

1. **State-specific tenancy rules**: The KB covers general principles; exact state rules (e.g., Rajasthan vs. Karnataka Rent Act) may differ
2. **Limitation period accuracy**: Estimates only — actual dates depend on cause of action interpretation
3. **Language quality**: LLM output in Tamil/Bengali/Marathi may be imperfect; English and Hindi/Hinglish are strongest
4. **Voice transcription**: Quality depends on audio clarity and accent; Sarvam AI option recommended for better Indian language support
5. **Rate limits**: Free-tier models may hit rate limits with heavy use; exponential backoff mitigates but doesn't eliminate
6. **No real-time law updates**: KB is static and manually maintained

---

## 💰 Cost Estimate (per conversation)

Based on test runs with Gemini Flash:
- Average tokens per conversation: ~3,000 input + ~2,000 output
- Gemini Flash pricing: Free tier (generous limits)
- At OpenAI gpt-4o-mini ($0.15/1M input, $0.60/1M output):
  - Per conversation: ~$0.0005 + $0.0012 = **~$0.0017 (~₹0.14)**
  - 1,000 conversations/day: **~$1.70/day (~₹142)**

---

## 📂 Project Structure

```
paisa-wapas/
  app.py                 # Gradio UI and conversation state machine
  llm.py                 # Model-agnostic wrapper (LiteLLM), retries, JSON parsing
  stt.py                 # Audio → text (Gemini | Sarvam)
  schemas.py             # Pydantic: CaseFile, Advice, Draft, KBEntry
  rules.py               # Deterministic logic: escalation, limitation, forum, proof
  kb/
    law_kb.yaml          # Curated legal knowledge base (20 entries)
    retrieve.py          # Filter KB entries by category + tags
  validator.py           # Post-generation citation checker + repealed-law blocker
  prompts/
    intake.md            # Intake conversation prompt
    advisor.md           # Legal advice prompt (KB-grounded)
    drafter.md           # Document drafting prompt (KB-grounded)
    opponent.md          # Practice mode role-play prompt
  tests/cases.jsonl      # 14 test cases
  run_tests.py           # End-to-end test runner
  outputs/               # Raw, unedited run outputs
  requirements.txt
  README.md
```

---

## 🧪 Running Tests

```bash
# Default model
python run_tests.py

# Different model
LLM_MODEL=openai/gpt-4o-mini python run_tests.py

# Outputs saved to outputs/<model>/
# Summary CSV: outputs/<model>/summary.csv
```

---

## 📜 License

Built for the Kuku AI Generalist Assignment (Problem 2). Prototype only — not for production legal use.
