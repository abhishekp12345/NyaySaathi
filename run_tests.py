"""Automated test runner for Paisa Wapas.

Runs each test case end-to-end and writes raw outputs.
Usage: LLM_MODEL=gemini/gemini-2.0-flash python run_tests.py
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent))

from schemas import CaseFile, IntakeResponse, RulesResult
from llm import chat, chat_json, get_model
from rules import run_rules
from kb.retrieve import get_entries_for_case
from validator import validate_and_fix, render_citations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")


def run_single_test(test_case: dict) -> dict:
    """Run a single test case end-to-end."""
    tc_id = test_case["id"]
    language = test_case.get("language") or test_case.get("user_language") or "English"
    turns = test_case["turns"]
    expected = test_case["expected"]

    result = {
        "id": tc_id,
        "model": get_model(),
        "language": language,
        "timestamp": datetime.now().isoformat(),
        "turns": [],
        "casefile": None,
        "rules_result": None,
        "advice": None,
        "draft": None,
        "validator_hits": [],
        "checks": {},
    }

    try:
        # ── Intake ───────────────────────────────────────────────────────
        casefile = CaseFile(user_language=language)
        intake_prompt = load_prompt("intake")
        intake_prompt = intake_prompt.replace("{user_language}", language)
        intake_prompt = intake_prompt.replace(
            "{casefile_schema_json}", str(CaseFile.model_json_schema())
        )

        for turn_text in turns:
            if turn_text.startswith("[AUDIO_FILE:"):
                result["turns"].append({"input": turn_text, "skipped": "audio test — needs audio file"})
                continue

            messages = [
                {"role": "system", "content": intake_prompt},
                {"role": "user", "content": (
                    f"Current CaseFile state:\n{casefile.model_dump_json(indent=2)}\n\n"
                    f"User says: {turn_text}"
                )},
            ]

            intake_resp = chat_json(messages, IntakeResponse)
            casefile = intake_resp.casefile
            casefile.user_language = language

            result["turns"].append({
                "input": turn_text,
                "casefile_after": casefile.model_dump(),
                "next_questions": intake_resp.next_questions,
                "escalation_flag": intake_resp.escalation_flag,
            })

            if intake_resp.escalation_flag:
                casefile.escalation_flag = intake_resp.escalation_flag
                break

        result["casefile"] = casefile.model_dump()

        # ── Rules ────────────────────────────────────────────────────────
        rules_result = run_rules(casefile)
        result["rules_result"] = rules_result.model_dump()

        # ── Advice (if not escalated) ────────────────────────────────────
        if not rules_result.escalation:
            kb_entries = get_entries_for_case(casefile)
            kb_ids = [e["id"] for e in kb_entries]

            advisor_prompt = load_prompt("advisor")
            advisor_prompt = advisor_prompt.replace("{user_language}", language)
            advisor_prompt = advisor_prompt.replace("{casefile_json}", casefile.model_dump_json(indent=2))
            advisor_prompt = advisor_prompt.replace("{rules_json}", rules_result.model_dump_json(indent=2))
            advisor_prompt = advisor_prompt.replace(
                "{kb_entries_json}", json.dumps(kb_entries, indent=2, ensure_ascii=False)
            )

            raw_advice = chat([{"role": "system", "content": advisor_prompt}], temperature=0.3)
            cleaned_advice, advice_hits = validate_and_fix(raw_advice, kb_ids)
            result["advice"] = cleaned_advice
            result["validator_hits"].extend([h.model_dump() for h in advice_hits])

            # ── Draft ────────────────────────────────────────────────────
            doc_type = rules_result.doc_type.value if rules_result.doc_type else "legal_notice"
            drafter_prompt = load_prompt("drafter")
            drafter_prompt = drafter_prompt.replace("{doc_type}", doc_type)
            drafter_prompt = drafter_prompt.replace("{user_language}", language)
            drafter_prompt = drafter_prompt.replace("{casefile_json}", casefile.model_dump_json(indent=2))
            drafter_prompt = drafter_prompt.replace("{rules_json}", rules_result.model_dump_json(indent=2))
            drafter_prompt = drafter_prompt.replace(
                "{kb_entries_json}", json.dumps(kb_entries, indent=2, ensure_ascii=False)
            )

            raw_draft = chat([{"role": "system", "content": drafter_prompt}], temperature=0.2)
            cleaned_draft, draft_hits = validate_and_fix(raw_draft, kb_ids)
            result["draft"] = cleaned_draft
            result["validator_hits"].extend([h.model_dump() for h in draft_hits])

        # ── Automated checks ─────────────────────────────────────────────
        checks = {}

        # Category check
        if expected.get("category"):
            detected = casefile.category.value if casefile.category else None
            checks["category_correct"] = detected == expected["category"]

        # Escalation check
        if "should_escalate" in expected:
            did_escalate = bool(casefile.escalation_flag or rules_result.escalation)
            checks["escalation_correct"] = did_escalate == expected["should_escalate"]

        # Forum check
        if expected.get("forum"):
            detected_forum = rules_result.forum.value if rules_result.forum else None
            checks["forum_correct"] = detected_forum == expected["forum"]

        # Must-not-contain
        if expected.get("must_not_contain"):
            all_text = json.dumps(result, ensure_ascii=False).lower()
            violations = []
            for forbidden in expected["must_not_contain"]:
                if forbidden.lower() in all_text:
                    violations.append(forbidden)
            checks["must_not_contain_passed"] = len(violations) == 0
            checks["must_not_contain_violations"] = violations

        # Validator hits count
        checks["validator_hits_count"] = len(result["validator_hits"])

        result["checks"] = checks

    except Exception as e:
        logger.error(f"Error in test {tc_id}: {e}", exc_info=True)
        result["error"] = str(e)

    return result


def main():
    model_name = get_model().replace("/", "_").replace(":", "_")
    output_dir = Path(__file__).parent / "outputs" / model_name
    output_dir.mkdir(parents=True, exist_ok=True)

    cases_file = Path(__file__).parent / "tests" / "cases.jsonl"
    with open(cases_file, "r", encoding="utf-8") as f:
        test_cases = [json.loads(line) for line in f if line.strip()]

    all_results = []
    print(f"\n{'='*60}")
    print(f"  Paisa Wapas Test Runner")
    print(f"  Model: {get_model()}")
    print(f"  Test cases: {len(test_cases)}")
    print(f"{'='*60}\n")

    for i, tc in enumerate(test_cases):
        tc_id = tc["id"]
        lang = tc.get("language") or tc.get("user_language") or "auto"
        print(f"  [{i+1}/{len(test_cases)}] Running {tc_id} ({lang})...", end=" ", flush=True)
        start = time.time()

        result = run_single_test(tc)
        elapsed = time.time() - start

        # Write individual result
        out_path = output_dir / f"{tc_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        # Status
        checks = result.get("checks", {})
        status = "[PASS]" if all(
            v for k, v in checks.items()
            if k.endswith("_correct") or k == "must_not_contain_passed"
        ) else "[FAIL]"
        print(f"{status} ({elapsed:.1f}s)")

        if checks.get("must_not_contain_violations"):
            print(f"     ⚠ Forbidden terms found: {checks['must_not_contain_violations']}")

        all_results.append(result)
        time.sleep(1)  # Small delay between API calls

    # ── Summary CSV ──────────────────────────────────────────────────────
    csv_path = output_dir / "summary.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "language", "category_correct", "escalation_correct",
            "forum_correct", "must_not_contain_passed",
            "validator_hits_count", "error"
        ])
        for r in all_results:
            c = r.get("checks", {})
            writer.writerow([
                r["id"],
                r["language"],
                c.get("category_correct", "N/A"),
                c.get("escalation_correct", "N/A"),
                c.get("forum_correct", "N/A"),
                c.get("must_not_contain_passed", "N/A"),
                c.get("validator_hits_count", 0),
                r.get("error", ""),
            ])

    # ── Final summary ────────────────────────────────────────────────────
    passed = sum(
        1 for r in all_results
        if all(
            v for k, v in r.get("checks", {}).items()
            if k.endswith("_correct") or k == "must_not_contain_passed"
        ) and "error" not in r
    )
    print(f"\n{'='*60}")
    print(f"  Results: {passed}/{len(all_results)} passed")
    print(f"  Outputs: {output_dir}")
    print(f"  Summary: {csv_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
