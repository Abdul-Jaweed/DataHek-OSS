"""Build + execute the teaching notebooks.

Converts each notebooks/NN_*.py (percent/light format) into an executed
notebooks/NN_*.ipynb, failing loudly on any cell error.

Usage (repo root):
    python notebooks/_build.py            # all notebooks
    python notebooks/_build.py 01 03      # selected prefixes
"""
import asyncio
import glob
import os
import sys

import nbformat
from nbclient import NotebookClient


def build_one(py_path: str) -> str:
    ipynb_path = py_path[:-3] + ".ipynb"
    source = open(py_path, encoding="utf-8").read()
    nb = nbformat.reads(_py_to_ipynb_json(source), as_version=4)

    client = NotebookClient(
        nb,
        timeout=180,
        kernel_name="datahek",
        resources={"metadata": {"path": os.path.dirname(py_path) or "."}},
    )
    client.execute()
    nbformat.write(nb, ipynb_path)
    return ipynb_path


def _py_to_ipynb_json(source: str) -> str:
    """Minimal percent-format ('# %%' / '# %% [markdown]') to ipynb conversion."""
    import json

    cells = []
    current_kind = "code"
    current: list[str] = []

    def flush():
        nonlocal current, current_kind
        text = "\n".join(current).strip("\n")
        if text.strip():
            if current_kind == "markdown":
                cells.append({
                    "cell_type": "markdown", "metadata": {},
                    "source": text.splitlines(keepends=True),
                })
            else:
                cells.append({
                    "cell_type": "code", "metadata": {}, "execution_count": None,
                    "outputs": [], "source": text.splitlines(keepends=True),
                })
        current = []

    for line in source.splitlines():
        if line.startswith("# %% [markdown]"):
            flush()
            current_kind = "markdown"
            continue
        if line.startswith("# %%"):
            flush()
            current_kind = "code"
            continue
        if current_kind == "markdown" and line.startswith("# "):
            current.append(line[2:])
            continue
        if current_kind == "markdown" and line.strip() == "#":
            current.append("")
            continue
        current.append(line)
    flush()

    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "DataHek (repo venv)", "language": "python", "name": "datahek"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(nb)


def main() -> int:
    prefixes = sys.argv[1:]
    paths = sorted(glob.glob("notebooks/[0-9][0-9]_*.py"))
    if prefixes:
        paths = [p for p in paths if any(os.path.basename(p).startswith(pref) for pref in prefixes)]
    failures = 0
    for py_path in paths:
        print(f"==> executing {py_path}")
        try:
            out = build_one(py_path)
            print(f"    wrote {out}")
        except Exception as exc:
            failures += 1
            print(f"    FAILED: {type(exc).__name__}: {str(exc)[:1500]}")
    print(f"\n{len(paths) - failures}/{len(paths)} notebooks executed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
