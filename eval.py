"""Measure accuracy on tests/cases.json.
Usage: python eval.py [--delay 8] [--only id1,id2] [--fresh]
Needs GEMINI_API_KEY set (same as the app). Finished cases are saved in eval_cache.json, so if a run
stops early (quota, busy server) just run it again: it continues with the cases still missing.
Use --fresh to ignore the saved results and re-run everything."""
import argparse
import csv
import hashlib
import json
import os
import time

import core

CACHE = "eval_cache.json"


def find_match(expected, tasks, used):
    for i, t in enumerate(tasks):
        if i in used:
            continue
        text = f"{t['description']} {t.get('source_quote') or ''}".lower()
        if any(k in text for k in expected["keywords"]):
            return i
    return None


def owner_ok(expected, got):
    got = (got or "").strip().lower()
    return got in core.GENERIC_OWNERS if expected is None else expected.lower() in got


def deadline_ok(expected, got):
    got = (got or "").strip()
    return got == expected if expected else not core.ISO_DATE.match(got)


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "n/a"


def score_case(c, result):
    flagged = {i["task_id"] for i in core.validate(result)}
    tasks, used = result["tasks"], set()
    s = dict(expected=len(c["tasks"]), found=len(tasks), matched=0, owner=0, deadline=0, tp=0, fp=0, fn=0)
    for exp in c["tasks"]:
        i = find_match(exp, tasks, used)
        if i is None:
            print(f"  [{c['id']}] MISSED task: {exp['keywords']}")
            continue
        used.add(i)
        t = tasks[i]
        ok_o, ok_d = owner_ok(exp["owner"], t.get("owner")), deadline_ok(exp["deadline"], t.get("deadline"))
        if not ok_o:
            print(f"  [{c['id']}] owner: expected {exp['owner']}, got {t.get('owner')}")
        if not ok_d:
            print(f"  [{c['id']}] deadline: expected {exp['deadline']}, got {t.get('deadline')}")
        pred = t["id"] in flagged
        if pred != exp["should_flag"]:
            print(f"  [{c['id']}] flag: expected {exp['should_flag']}, got {pred} ('{t['description'][:50]}')")
        s["matched"] += 1
        s["owner"] += ok_o
        s["deadline"] += ok_d
        s["tp"] += pred and exp["should_flag"]
        s["fp"] += pred and not exp["should_flag"]
        s["fn"] += (not pred) and exp["should_flag"]
    if len(tasks) - len(used):
        print(f"  [{c['id']}] {len(tasks) - len(used)} extra task(s) not in the answer key")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=8)
    ap.add_argument("--cases", default="tests/cases.json")
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--fresh", action="store_true", help="ignore saved results")
    args = ap.parse_args()

    cases = json.load(open(args.cases, encoding="utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    cache = {} if args.fresh or not os.path.exists(CACHE) else json.load(open(CACHE, encoding="utf-8"))
    client, called = None, False

    stats = {}
    for c in cases:
        h = hashlib.md5(json.dumps(c, sort_keys=True).encode()).hexdigest()
        if cache.get(c["id"], {}).get("hash") == h:
            stats[c["id"]] = cache[c["id"]]["stats"]
            print(f"[{c['id']}] (saved result from an earlier run)")
            continue
        if called:
            time.sleep(args.delay)
        try:
            client = client or core.get_client()
            called = True
            result = core.extract(client, c["transcript"], c["meeting_date"])
        except Exception as e:
            print(f"[{c['id']}] ERROR: {e}")
            if "Daily free quota" in str(e):
                break
            continue
        s = score_case(c, result)
        stats[c["id"]] = s
        cache[c["id"]] = {"hash": h, "stats": s}
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=1)
        print(f"[{c['id']}] expected {s['expected']} | found {s['found']} | matched {s['matched']} | "
              f"owner ok {s['owner']} | deadline ok {s['deadline']}")

    tot = {k: sum(s[k] for s in stats.values()) for k in ("expected", "found", "matched", "owner", "deadline", "tp", "fp", "fn")}
    with open("eval_report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case", "expected", "found", "matched", "owner_ok", "deadline_ok"])
        for cid, s in stats.items():
            w.writerow([cid, s["expected"], s["found"], s["matched"], s["owner"], s["deadline"]])

    print("\n===== RESULTS =====")
    print(f"Transcripts evaluated: {len(stats)}/{len(cases)}" + ("" if len(stats) == len(cases) else "   <-- run again to finish the rest"))
    print(f"Task recall (real tasks found):     {pct(tot['matched'], tot['expected'])}")
    print(f"Task precision (found tasks real):  {pct(tot['matched'], tot['found'])}")
    print(f"Owner accuracy (matched tasks):     {pct(tot['owner'], tot['matched'])}")
    print(f"Deadline accuracy (matched tasks):  {pct(tot['deadline'], tot['matched'])}")
    print(f"Flagging recall (unclear caught):   {pct(tot['tp'], tot['tp'] + tot['fn'])}")
    print(f"Flagging precision (flags correct): {pct(tot['tp'], tot['tp'] + tot['fp'])}")
    print("Saved eval_report.csv")


if __name__ == "__main__":
    main()
