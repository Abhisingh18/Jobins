"""Flask API backend for the agent tracking dashboard.

Read-only system/status endpoints plus a launch endpoint that runs the agent
as a subprocess (single concurrent run). The Next.js frontend polls these.

Run:  .venv\\Scripts\\python.exe dashboard\\api\\dashboard_api.py   (port 8788)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests
from flask import Flask, jsonify, request

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACES_DIR = REPO_ROOT / "traces"
LIVE_LOG = TRACES_DIR / "live_run.log"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

app = Flask(__name__)

# one dashboard-launched agent process at a time
_current_run: dict = {"proc": None, "label": "", "started": 0.0}


@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


def _ollama_status() -> dict:
    try:
        v = requests.get(f"{OLLAMA_HOST}/api/version", timeout=3).json()
        tags = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3).json()
        models = [m.get("name") for m in tags.get("models", [])]
        return {"up": True, "version": v.get("version", "?"), "models": models}
    except requests.exceptions.RequestException as exc:
        return {"up": False, "error": type(exc).__name__, "models": []}


def _docker_status() -> dict:
    try:
        out = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return {"up": True, "version": out.stdout.strip()}
        return {"up": False, "error": (out.stderr or "daemon not reachable")[:120]}
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return {"up": False, "error": type(exc).__name__}


def _agent_run_status() -> dict:
    proc = _current_run["proc"]
    if proc is not None and proc.poll() is None:
        return {
            "running": True,
            "label": _current_run["label"],
            "elapsed_seconds": round(time.time() - _current_run["started"], 1),
            "pid": proc.pid,
        }
    finished = proc is not None
    return {
        "running": False,
        "last_label": _current_run["label"] if finished else "",
        "last_exit_code": proc.returncode if finished else None,
    }


def _disk(drive: str) -> dict:
    try:
        usage = shutil.disk_usage(drive)
        return {"free_gb": round(usage.free / 1e9, 1),
                "total_gb": round(usage.total / 1e9, 1)}
    except OSError:
        return {"free_gb": None, "total_gb": None}


@app.get("/api/status")
def status():
    return jsonify({
        "time": time.time(),
        "ollama": _ollama_status(),
        "docker": _docker_status(),
        "agent": _agent_run_status(),
        "disk": {"C": _disk("C:\\"), "F": _disk("F:\\")},
        "budget_config": {
            "max_llm_calls": int(os.environ.get("MAX_LLM_CALLS", "10")),
            "max_cost_usd": float(os.environ.get("MAX_COST_USD", "0.20")),
            "price_per_1k_tokens": float(os.environ.get("MOCK_PRICE_PER_1K_TOKENS", "0.01")),
            "model": os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
        },
    })


def _load_runs() -> list[dict]:
    runs = []
    if TRACES_DIR.exists():
        for f in sorted(TRACES_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            data["source_file"] = f.name
            data["modified"] = f.stat().st_mtime
            runs.append(data)
    return runs


@app.get("/api/runs")
def runs():
    summaries = []
    for r in _load_runs():
        b = r.get("budget", {})
        summaries.append({
            "id": r.get("id", r.get("source_file")),
            "source_file": r.get("source_file"),
            "kind": r.get("kind", "custom"),
            "task": r.get("task", ""),
            "status": r.get("status", "?"),
            "stop_reason": r.get("stop_reason", ""),
            "final_answer": (str(r.get("final_answer")) or "")[:400],
            "steps_completed": r.get("steps_completed", 0),
            "replans": len(r.get("replanning_events", [])),
            "llm_calls_used": b.get("llm_calls_used"),
            "max_llm_calls": b.get("max_llm_calls"),
            "cost_used_usd": b.get("cost_used_usd"),
            "max_cost_usd": b.get("max_cost_usd"),
            "elapsed_seconds": r.get("elapsed_seconds"),
            "modified": r.get("modified"),
        })
    summaries.sort(key=lambda x: x.get("modified") or 0, reverse=True)
    return jsonify(summaries)


@app.get("/api/runs/<source_file>")
def run_detail(source_file: str):
    safe = Path(source_file).name  # no path traversal
    f = TRACES_DIR / safe
    if not f.exists() or f.suffix != ".json":
        return jsonify({"error": "not found"}), 404
    return jsonify(json.loads(f.read_text(encoding="utf-8")))


@app.post("/api/launch")
def launch():
    if _current_run["proc"] is not None and _current_run["proc"].poll() is None:
        return jsonify({"error": "a run is already in progress"}), 409

    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "task")
    if mode == "suite":
        args = [str(VENV_PYTHON), "main.py", "--all-tests"]
        label = "5-task evaluation suite"
    else:
        task = (body.get("task") or "").strip()
        if not task:
            return jsonify({"error": "task text is required"}), 400
        args = [str(VENV_PYTHON), "main.py", task]
        label = task[:120]

    TRACES_DIR.mkdir(exist_ok=True)
    log_handle = open(LIVE_LOG, "w", encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        args, cwd=str(REPO_ROOT), stdout=log_handle,
        stderr=subprocess.STDOUT, env=env,
    )
    _current_run.update({"proc": proc, "label": label, "started": time.time()})
    return jsonify({"launched": True, "pid": proc.pid, "label": label})


@app.get("/api/live")
def live():
    log_lines: list[str] = []
    if LIVE_LOG.exists():
        try:
            log_lines = LIVE_LOG.read_text(encoding="utf-8", errors="replace") \
                                .splitlines()[-120:]
        except OSError:
            log_lines = ["(log unreadable)"]
    return jsonify({**_agent_run_status(), "log": log_lines})


if __name__ == "__main__":
    print(f"Dashboard API on http://localhost:8788 (repo: {REPO_ROOT})")
    app.run(host="127.0.0.1", port=8788, debug=False)
