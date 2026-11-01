"""A stand-in for `claude -p`: reads the prompt (last argv), logs the call, answers from canned rules."""
import json, os, sys
prompt = sys.argv[-1] if len(sys.argv) > 1 and not sys.argv[-1].endswith("fake_llm.py") else sys.stdin.buffer.read().decode("utf-8")
with open(os.environ["FAKE_LLM_LOG"], "a", encoding="utf-8") as f:
    f.write(prompt[:40].replace("\n", " ") + "\n")
mode = os.environ.get("FAKE_LLM_MODE", "ok")
if mode == "crash":
    sys.exit(3)
if "map a person's status update" in prompt:
    upd = prompt.split("Update:")[1].lower()
    if "terminé" in upd or "termine" in upd:
        print('Sure! {"id": "T-001", "status": "done"}')
    elif "hallucinate" in upd:
        print('{"id": "T-999", "status": "done"}')
    elif "weird" in upd:
        print('{"id": "T-001", "status": "finished-ish"}')
    else:
        print('{"id": null, "status": null}')
elif "Write 3-4 plain sentences" in prompt:
    print("The project is 50 percent complete." if mode == "ok" else "The project is 77 percent complete and growing.")
elif "CALCULATED fields" in prompt:
    print(json.dumps([{"name": "days_open", "type": "number", "formula": "days_since(created)", "why": "How long work sits."},
                      {"name": "evil", "type": "number", "formula": "__import__('os').getcwd()", "why": "x"},
                      {"name": "ghost", "type": "number", "formula": "nonexistent + 1", "why": "x"},
                      {"name": "status", "type": "string", "formula": "1", "why": "clash"},
                      {"name": "late", "type": "string", "formula": "'LATE' if is_overdue else 'ok'", "why": "Shows lateness."}]))
