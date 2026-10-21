"""Usage: python cli.py transcript.txt [YYYY-MM-DD]"""
import sys
import core


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    transcript = open(sys.argv[1], encoding="utf-8").read()
    meeting_date = sys.argv[2] if len(sys.argv) > 2 else None
    result = core.extract(core.get_client(), transcript, meeting_date)

    issues = core.validate(result)
    if issues:
        print(f"\n{len(issues)} item(s) need clarification (press Enter to skip):")
        answers = {}
        for iss in issues:
            val = input(f"[{iss['task_id']}] {iss['question']}\n> ")
            answers.setdefault(iss["task_id"], {})[iss["field"]] = val
        core.apply_clarifications(result, answers)

    print("\nSUMMARY:", result["summary"])
    print("\nDECISIONS:")
    for d in result["decisions"]:
        print(" -", d.get("decision"))
    print("\nTASKS:")
    for t in result["tasks"]:
        print(f" - {t['id']}: {t['description']} | {t['owner']} | {t['deadline']} | {t['priority']}")
    open("tasks.csv", "w", encoding="utf-8").write(core.tasks_to_csv(result))
    print("\nSaved tasks.csv")


if __name__ == "__main__":
    main()
