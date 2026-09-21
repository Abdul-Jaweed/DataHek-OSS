"""E2E runner: asks each question through DataHek, fetches the executed SQL from
checkpoints, re-executes it directly against InsForge, and compares rows."""
import argparse
import json
import pathlib

import sys as _sys

if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import re
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal

import psycopg

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from queries import QUERIES

API = "http://localhost:8000"
CONN_ID = "conn_000001a0c3c99dfede7287f9578f44e693fed7c7"
HERE = pathlib.Path(__file__).parent
RESULTS = HERE / "results.jsonl"

CFG = json.loads(
    pathlib.Path(r"C:\Users\azcom\AppData\Local\Temp\opencode\insforge-conn.json")
    .read_text(encoding="utf-8"))["insforge"]
DSN = (f"host={CFG['host']} port={CFG['port']} dbname={CFG['database']} "
       f"user={CFG['username']} password={CFG['password']} "
       f"sslmode={CFG.get('sslmode', 'prefer')} connect_timeout=15")


def ask(question: str, timeout: float = 300.0):
    body = json.dumps({"question": question, "connection_id": CONN_ID}).encode()
    req = urllib.request.Request(f"{API}/ask", data=body,
                                 headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            data = json.loads(exc.read() or b"{}")
        except Exception:
            data = {"message": "unparseable error body"}
    except Exception as exc:  # timeout / connection error
        return 0, {"message": f"client error: {exc}"}, time.perf_counter() - started
    return status, data, time.perf_counter() - started


def latest_checkpoint(question: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{API}/checkpoints?limit=10", timeout=30) as resp:
            items = json.loads(resp.read())
    except Exception:
        return None
    for item in items:
        if item.get("question") == question:
            return item
    return None


def normalise(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def run_sql(sql: str):
    stripped = sql.strip().rstrip(";")
    if not re.match(r"^\s*(select|with)\b", stripped, re.I) or ";" in stripped:
        raise ValueError("refusing unsafe SQL")
    conn = psycopg.connect(DSN, autocommit=True)
    try:
        cur = conn.execute(stripped)
        columns = [d.name for d in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
    finally:
        conn.close()
    return columns, rows


def val_eq(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def rows_match(dh_rows: list[dict], gt_rows: list[tuple], ordered: bool) -> tuple[bool, str]:
    if len(dh_rows) != len(gt_rows):
        return False, f"row count {len(dh_rows)} != {len(gt_rows)}"
    dh = [list(r.values()) for r in dh_rows]
    gt = [[normalise(v) for v in row] for row in gt_rows]
    if not ordered:
        dh = sorted(dh, key=lambda r: json.dumps(r, default=str))
        gt = sorted(gt, key=lambda r: json.dumps(r, default=str))
    for i, (a, b) in enumerate(zip(dh, gt)):
        if len(a) != len(b):
            return False, f"column count differs at row {i}"
        for j, (x, y) in enumerate(zip(a, b)):
            if not val_eq(x, y):
                return False, f"row {i} col {j}: {x!r} != {y!r}"
    return True, "ok"


def run_one(qid: int, category: str, question: str, expect: str) -> dict:
    status, data, latency = ask(question)
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
    parser.add_argument("--only", type=str, default="", help="comma-separated ids")
    parser.add_argument("--from-id", type=int, default=1)
    parser.add_argument("--to-id", type=int, default=10_000)
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

    with RESULTS.open("a", encoding="utf-8") as fh:
        for qid, category, question, expect in selected:
            outcome = run_one(qid, category, question, expect)
            fh.write(json.dumps(outcome) + "\n")
            fh.flush()
            done[qid] = outcome
            label = question[:60].replace("\n", " ")
            print(f"[{qid:3d}] {outcome['verdict']:<22} {outcome['latency_s']:>6.1f}s  {label}",
                  flush=True)

    counts = {}
    for rec in done.values():
        counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1
    print("\nverdicts so far:", json.dumps(counts, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
