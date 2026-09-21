"""Parallel E2E runner — same verdicts as run_suite, N workers, wider checkpoint window."""
import argparse
import json
import pathlib
import re
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from queries import QUERIES
from run_suite import API, ask, rows_match, run_sql

HERE = pathlib.Path(__file__).parent
RESULTS = HERE / "results.jsonl"
PRINT_LOCK = threading.Lock()


def latest_checkpoint(question: str, window: int = 200) -> dict | None:
    try:
        with urllib.request.urlopen(f"{API}/checkpoints?limit={window}", timeout=60) as resp:
            items = json.loads(resp.read())
    except Exception:
        return None
    for item in items:
        if item.get("question") == question:
            return item
    return None


def check_steps(steps: list) -> tuple[bool, str] | None:
    checked = 0
    for step in steps:
        if step.get("error"):
            return False, f"step failed: {step['question'][:40]}: {step['error'][:80]}"
        if not step.get("sql") or step.get("rows") is None:
            return None
        _cols, gt_rows = run_sql(step["sql"])
        dh_rows = step["rows"]
        if len(gt_rows) > len(dh_rows):
            gt_rows = gt_rows[:len(dh_rows)]
        ok, detail = rows_match(dh_rows, gt_rows, "order by" in step["sql"].lower())
        if not ok:
            return False, f"step '{step['question'][:40]}': {detail}"
        checked += 1
    return (checked > 0), ""


def run_one(qid: int, category: str, question: str, expect: str) -> dict:
    status, data, latency = ask(question, timeout=600.0)
    outcome = {
        "id": qid, "category": category, "question": question[:200], "expect": expect,
        "status": status, "latency_s": round(latency, 2),
        "answer": (data.get("answer") or data.get("message") or "")[:300],
        "error_code": data.get("code"),
        "row_count": data.get("row_count"), "truncated": data.get("truncated"),
        "rows_len": len(data["rows"]) if isinstance(data.get("rows"), list) else None,
        "columns_len": len(data["columns"]) if isinstance(data.get("columns"), list) else None,
        "clarification": bool(data.get("clarification")),
        "sql": None, "verdict": "pending", "detail": "",
    }
    if status == 202:
        outcome["verdict"] = "approval"
        return outcome
    if status == 0 or status >= 400:
        outcome["verdict"] = "error"
        return outcome
    if data.get("clarification"):
        outcome["verdict"] = "clarification"
        return outcome
    if isinstance(data.get("steps"), list) and data["steps"]:
        result = check_steps(data["steps"])
        if result is None:
            outcome["verdict"] = "answered_no_rows"
        else:
            ok, detail = result
            outcome["verdict"] = "match" if ok else "mismatch"
            outcome["detail"] = f"multi-step {detail}"[:300]
        return outcome
    if data.get("rows") is not None and data.get("columns"):
        checkpoint = latest_checkpoint(question)
        if checkpoint and checkpoint.get("sql"):
            outcome["sql"] = checkpoint["sql"]
            try:
                _cols, gt_rows = run_sql(checkpoint["sql"])
            except Exception as exc:
                outcome["verdict"] = "gt_failed"
                outcome["detail"] = str(exc)[:300]
                return outcome
            ordered = "order by" in checkpoint["sql"].lower()
            has_aggregate = re.search(r"\b(count|sum|avg|min|max)\s*\(", checkpoint["sql"],
                                      re.IGNORECASE) is not None
            if not ordered and "limit" in checkpoint["sql"].lower() and not has_aggregate:
                ok = (len(data["rows"]) == len(gt_rows)
                      and outcome["columns_len"] == len(_cols))
                outcome["verdict"] = "match_sampled" if ok else "mismatch"
                outcome["detail"] = "unordered raw rows; compared counts only"
                return outcome
            ok, detail = rows_match(data["rows"], gt_rows, ordered)
            outcome["verdict"] = "match" if ok else "mismatch"
            outcome["detail"] = detail
            return outcome
        outcome["verdict"] = "answered_no_checkpoint"
        return outcome
    outcome["verdict"] = "answered_no_rows"
    return outcome


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only", type=str, default="")
    parser.add_argument("--from-id", type=int, default=1)
    parser.add_argument("--to-id", type=int, default=100_000)
    args = parser.parse_args()

    only = {int(x) for x in args.only.split(",") if x.strip()} if args.only else None
    selected = [q for q in QUERIES
                if (only and q[0] in only) or (not only and args.from_id <= q[0] <= args.to_id)]

    done = {}
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["id"]] = rec
    selected = [q for q in selected if q[0] not in done]
    print(f"running {len(selected)} queries with {args.workers} workers", flush=True)

    started = time.perf_counter()
    lock = threading.Lock()
    with RESULTS.open("a", encoding="utf-8") as fh, \
            ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, *q): q[0] for q in selected}
        for future in futures:
            qid = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:
                outcome = {"id": qid, "verdict": "error", "latency_s": 0,
                           "detail": f"runner: {exc}"[:300], "question": "", "category": "",
                           "expect": "", "status": 0, "answer": "", "error_code": "RUNNER",
                           "row_count": None, "truncated": None, "rows_len": None,
                           "columns_len": None, "clarification": False, "sql": None}
            with lock:
                fh.write(json.dumps(outcome) + "\n")
                fh.flush()
                done[qid] = outcome
            label = outcome.get("question", "")[:58].replace("\n", " ")
            with PRINT_LOCK:
                print(f"[{qid:3d}] {outcome['verdict']:<22} {outcome['latency_s']:>6.1f}s  {label}",
                      flush=True)

    counts = {}
    for rec in done.values():
        counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1
    print(f"\nelapsed {time.perf_counter() - started:.0f}s  verdicts:", json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()
