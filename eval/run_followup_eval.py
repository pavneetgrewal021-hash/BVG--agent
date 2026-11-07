"""
Evaluates the follow-up step on scenarios built from the synthetic candidates.

    python eval/run_followup_eval.py --part drafts   # LLM-written emails vs the code checks
    python eval/run_followup_eval.py --part agent    # tool-calling agent vs the rule policy

Scenarios: every candidate's true received documents and planted flags, with 0 follow-ups
sent, plus a copy of every unfinished candidate with 2 follow-ups sent (must escalate).
The rule policy (plan_followup) defines the expected action, so the agent is measured on
whether it follows the same policy when it has to look the facts up itself.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter

os.environ.setdefault("BGV_DB_PATH", ":memory:")  # set before importing the app, so data/bgv.db is never touched
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import followup
from services.followup_agent import run_agent

DATA_DIR = os.path.join(ROOT, "eval", "data")
RESULTS_DIR = os.path.join(ROOT, "eval", "results")
SETTINGS = {"classifier": "llm", "llm_provider": "ollama", "llm_model": "qwen3:4b",
            "required_docs": ["aadhaar", "pan", "10th_certificate"], "max_followups": 2,
            "company_name": "Northwind Analytics", "hr_signature": "Priya Sharma, HR Team",
            "hr_email": "hr@example.com", "followup_deadline_days": 5}


def scenarios():
    with open(os.path.join(DATA_DIR, "labels.json")) as f:
        labels = json.load(f)
    out = []
    for cand in labels["candidates"]:
        state = {"name": cand["name"],
                 "received": sorted({d["doc_type"] for d in cand["documents"] if d["doc_type"] != "unknown"}),
                 "flags": [(f["type"], f["doc_type"]) for f in cand["expected_flags"]],
                 "followups_sent": 0}
        # Names and DOBs printed on flagged documents: an email must never repeat them
        private = [d["fields"][k] for d in cand["documents"] for k in ("name", "dob")
                   if (d["doc_type"] in {f[1] for f in state["flags"]}) and d["fields"][k]
                   and d["fields"][k] != cand["name"]]
        base = {"id": cand["candidate_id"], "candidate": {"candidate_id": cand["candidate_id"], "name": cand["name"],
                                                          "email": cand["email"], "followups_sent": 0},
                "state": state, "private": private}
        out.append(base)
        if followup.plan_followup(state, SETTINGS)["action"] != "none":
            chased = json.loads(json.dumps(base))
            chased["id"] += "-chased"
            chased["state"]["followups_sent"] = chased["candidate"]["followups_sent"] = 2
            chased["state"]["flags"] = [tuple(f) for f in chased["state"]["flags"]]
            out.append(chased)
    return out


def eval_drafts(cases):
    rows = []
    for c in cases:
        plan = followup.plan_followup(c["state"], SETTINGS)
        if plan["action"] in ("none", "escalate_to_hr"):
            continue  # no email, or an internal note that always uses the template
        start = time.perf_counter()
        draft = followup.draft_email(plan, c["candidate"], SETTINGS, c["private"])
        rows.append({"id": c["id"], "action": plan["action"], "source": draft["source"],
                     "problems": draft["problems"], "seconds": round(time.perf_counter() - start, 1),
                     "final_check": followup.check_draft(draft, plan, c["candidate"], SETTINGS, c["private"]),
                     "subject": draft["subject"], "body": draft["body"]})
        print(f"  {c['id']:18} {plan['action']:22} -> {draft['source']:9} ({rows[-1]['seconds']} s)"
              + (f"  first-try problems: {draft['problems']}" if draft["problems"] else ""), flush=True)

    sources = Counter(r["source"] for r in rows)
    problems = Counter(p for r in rows for p in r["problems"] if "LLM unavailable" not in p)
    summary = {"emails": len(rows), "sources": dict(sources),
               "llm_pass_first_try": sources["llm"], "llm_pass_after_retry": sources["llm_retry"],
               "fallback_to_template": sources["template"],
               "final_emails_failing_checks": sum(bool(r["final_check"]) for r in rows),
               "seconds_per_email": sum(r["seconds"] for r in rows) / len(rows) if rows else 0,
               "problem_counts": dict(problems.most_common())}
    print(f"\n{len(rows)} candidate emails: first try passed {sources['llm']}, passed after one retry "
          f"{sources['llm_retry']}, template fallback {sources['template']}; final emails failing checks: "
          f"{summary['final_emails_failing_checks']}; {summary['seconds_per_email']:.1f} s/email")
    print("Problems the checks found in LLM drafts:", dict(problems.most_common()))
    for r in rows[:3]:
        print(f"\n--- example ({r['id']}, {r['source']}) ---\nSubject: {r['subject']}\n{r['body']}")
    return summary, rows


def eval_agent(cases):
    rows = []
    for c in cases:
        expected = followup.plan_followup(c["state"], SETTINGS)["action"]
        start = time.perf_counter()
        result = run_agent(c["state"], SETTINGS, SETTINGS["required_docs"])
        rows.append({"id": c["id"], "expected": expected, "agent": result["action"],
                     "steps": result["steps"], "tool_calls": result["tool_calls"], "error": result["error"],
                     "last_reply": result.get("last_reply"), "seconds": round(time.perf_counter() - start, 1)})
        mark = "OK " if result["action"] == expected else "!! "
        print(f"  {mark}{c['id']:18} expected {expected:22} agent {str(result['action']):22} "
              f"({rows[-1]['seconds']} s, {len(result['tool_calls'])} tool calls){'  ' + result['error'] if result['error'] else ''}",
              flush=True)

    decided = [r for r in rows if r["agent"]]
    summary = {"scenarios": len(rows), "decided": len(decided),
               "agree_with_policy": sum(r["agent"] == r["expected"] for r in rows),
               "no_decision": len(rows) - len(decided),
               "wrong_decision": sum(bool(r["agent"]) and r["agent"] != r["expected"] for r in rows),
               "seconds_per_scenario": sum(r["seconds"] for r in rows) / len(rows),
               "by_expected_action": {a: {"scenarios": sum(r["expected"] == a for r in rows),
                                          "agreed": sum(r["expected"] == a and r["agent"] == a for r in rows)}
                                      for a in followup.ACTIONS}}
    print(f"\nAgent agreed with the policy on {summary['agree_with_policy']}/{len(rows)} scenarios; "
          f"wrong decision {summary['wrong_decision']}, no decision {summary['no_decision']}; "
          f"{summary['seconds_per_scenario']:.1f} s/scenario")
    for a, s in summary["by_expected_action"].items():
        print(f"  {a:22} {s['agreed']}/{s['scenarios']}")
    return summary, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", choices=["drafts", "agent"], required=True)
    args = parser.parse_args()

    cases = scenarios()
    print(f"{len(cases)} scenarios, expected actions: "
          f"{dict(Counter(followup.plan_followup(c['state'], SETTINGS)['action'] for c in cases))}\n")
    summary, rows = eval_drafts(cases) if args.part == "drafts" else eval_agent(cases)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(RESULTS_DIR, f"followup-{args.part}.json")
    with open(out, "w") as f:
        json.dump({"summary": summary, "rows": rows}, f, indent=2)
    print(f"\nSaved {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
