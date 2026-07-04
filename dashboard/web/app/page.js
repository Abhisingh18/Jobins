"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API = "http://localhost:8788";

function StatusPill({ state, label }) {
  return (
    <span className={`pill ${state}`}>
      <span className="dot" />
      {label}
    </span>
  );
}

function Meter({ used, max, money }) {
  if (used == null || !max) return <span className="meter-label">—</span>;
  const pct = Math.min(100, (used / max) * 100);
  const over = used > max;
  return (
    <span>
      <span className="meter">
        <i className={over ? "over" : ""} style={{ width: `${pct}%` }} />
      </span>
      <span className="meter-label">
        {money ? `$${Number(used).toFixed(4)}/$${max}` : `${used}/${max}`}
      </span>
    </span>
  );
}

function TraceView({ detail }) {
  if (!detail) return <div className="empty">loading trace…</div>;
  return (
    <div>
      {(detail.trace || []).map((s) => (
        <div className="step" key={s.step}>
          <div className="no">{s.step}</div>
          <div className="body">
            <div>
              <b>THINK:</b> {s.thought}
              {s.replanned && <span className="tag replan">REPLANNED</span>}
            </div>
            {s.action ? (
              <div className="mono">
                ACT: {s.action.tool}({JSON.stringify(s.action.args || {}).slice(0, 160)})
              </div>
            ) : (
              <div className="mono">ACT: final_answer</div>
            )}
            <div className="mono">OBS: {(s.observation || "").slice(0, 220)}</div>
          </div>
        </div>
      ))}
      <div className="answer">
        <b>Final answer:</b> {String(detail.final_answer ?? "—")}
      </div>
    </div>
  );
}

export default function Page() {
  const [status, setStatus] = useState(null);
  const [runs, setRuns] = useState([]);
  const [openRun, setOpenRun] = useState(null);
  const [detail, setDetail] = useState(null);
  const [task, setTask] = useState("");
  const [live, setLive] = useState(null);
  const [launchErr, setLaunchErr] = useState("");
  const [apiDown, setApiDown] = useState(false);
  const consoleRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([
        fetch(`${API}/api/status`).then((x) => x.json()),
        fetch(`${API}/api/runs`).then((x) => x.json()),
      ]);
      setStatus(s);
      setRuns(r);
      setApiDown(false);
    } catch {
      setApiDown(true);
    }
  }, []);

  const pollLive = useCallback(async () => {
    try {
      const l = await fetch(`${API}/api/live`).then((x) => x.json());
      setLive(l);
    } catch {
      /* API poll failed; status banner already shows apiDown */
    }
  }, []);

  useEffect(() => {
    refresh();
    pollLive();
    const t1 = setInterval(refresh, 4000);
    const t2 = setInterval(pollLive, 2500);
    return () => {
      clearInterval(t1);
      clearInterval(t2);
    };
  }, [refresh, pollLive]);

  useEffect(() => {
    if (consoleRef.current)
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
  }, [live]);

  useEffect(() => {
    if (!openRun) return;
    setDetail(null);
    fetch(`${API}/api/runs/${openRun}`)
      .then((x) => x.json())
      .then(setDetail)
      .catch(() => setDetail({ trace: [], final_answer: "(failed to load)" }));
  }, [openRun]);

  async function launch(mode) {
    setLaunchErr("");
    try {
      const res = await fetch(`${API}/api/launch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mode === "suite" ? { mode } : { mode, task }),
      });
      const data = await res.json();
      if (!res.ok) setLaunchErr(data.error || "launch failed");
      else pollLive();
    } catch {
      setLaunchErr("API not reachable — is dashboard_api.py running?");
    }
  }

  const running = live?.running;
  const ol = status?.ollama;
  const dk = status?.docker;

  return (
    <div className="shell">
      <div className="topbar">
        <h1>Agent Control Center</h1>
        <span className="sub">
          resource-constrained planning loop · auto-refresh 4s
          {apiDown && <span className="err-note"> · API OFFLINE</span>}
        </span>
      </div>

      <div className="grid4">
        <div className="card">
          <h3>Ollama LLM Server</h3>
          <StatusPill
            state={ol?.up ? "ok" : "bad"}
            label={ol?.up ? `Running v${ol.version}` : "Down"}
          />
          <div className="kv">
            Models: <b>{ol?.models?.length ? ol.models.join(", ") : "none"}</b>
          </div>
        </div>

        <div className="card">
          <h3>Docker Engine</h3>
          <StatusPill
            state={dk?.up ? "ok" : "warn"}
            label={dk?.up ? `Running v${dk.version}` : "Not running"}
          />
          <div className="kv">
            Needed only for the containerized run
          </div>
        </div>

        <div className="card">
          <h3>Agent Process</h3>
          <StatusPill
            state={running ? "run" : "idle"}
            label={running ? `Running · ${live.elapsed_seconds}s` : "Idle"}
          />
          <div className="kv">
            {running ? (
              <>Task: <b>{live.label}</b></>
            ) : live?.last_label ? (
              <>Last: <b>{live.last_label}</b> (exit {String(live.last_exit_code)})</>
            ) : (
              "No run this session"
            )}
          </div>
        </div>

        <div className="card">
          <h3>Budget / Disk</h3>
          <div className="kv">
            Budget: <b>{status?.budget_config?.max_llm_calls} calls · $
            {status?.budget_config?.max_cost_usd}</b> · {status?.budget_config?.model}
          </div>
          <div className="kv">
            F: <b>{status?.disk?.F?.free_gb ?? "?"} GB free</b> · C:{" "}
            <b>{status?.disk?.C?.free_gb ?? "?"} GB free</b>
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Launch a run</h3>
        <div className="launch">
          <input
            placeholder='e.g. "What is the population of Japan? Use web search."'
            value={task}
            onChange={(e) => setTask(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && task && !running && launch("task")}
            disabled={running}
          />
          <button
            className="btn primary"
            onClick={() => launch("task")}
            disabled={running || !task.trim()}
          >
            Run task
          </button>
          <button
            className="btn ghost"
            onClick={() => launch("suite")}
            disabled={running}
          >
            Run 5-task suite
          </button>
        </div>
        {launchErr && <div className="err-note">{launchErr}</div>}
        {(running || live?.log?.length > 0) && (
          <div className="console" ref={consoleRef}>
            {(live?.log || []).map((ln, i) => (
              <div key={i} className={/FINAL|BUDGET|REPLAN/.test(ln) ? "hl" : ""}>
                {ln || " "}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="section-title">
        Run history
        <span className="count">
          {runs.length} traces · from traces/*.json
        </span>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {runs.length === 0 ? (
          <div className="empty">No runs recorded yet — launch one above.</div>
        ) : (
          <table className="runs">
            <thead>
              <tr>
                <th>Task</th>
                <th>Kind</th>
                <th>Status</th>
                <th>LLM calls</th>
                <th>Cost</th>
                <th>Replans</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <FragmentRow
                  key={r.source_file}
                  r={r}
                  open={openRun === r.source_file}
                  onToggle={() =>
                    setOpenRun(openRun === r.source_file ? null : r.source_file)
                  }
                  detail={detail}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function FragmentRow({ r, open, onToggle, detail }) {
  return (
    <>
      <tr className="rowbtn" onClick={onToggle}>
        <td style={{ maxWidth: 340 }}>
          {(r.task || "").slice(0, 90)}
          {(r.task || "").length > 90 ? "…" : ""}
        </td>
        <td>{r.kind}</td>
        <td>
          <span className={`badge ${r.status}`}>{r.status}</span>
          <div style={{ fontSize: 11, color: "var(--ink-3)", marginTop: 2 }}>
            {r.stop_reason}
          </div>
        </td>
        <td><Meter used={r.llm_calls_used} max={r.max_llm_calls} /></td>
        <td><Meter used={r.cost_used_usd} max={r.max_cost_usd} money /></td>
        <td>{r.replans > 0 ? <span className="badge partial">{r.replans}</span> : "0"}</td>
        <td className="meter-label">
          {r.elapsed_seconds ? `${Math.round(r.elapsed_seconds)}s` : "—"}
        </td>
      </tr>
      {open && (
        <tr className="trace">
          <td colSpan={7}>
            <TraceView detail={detail} />
          </td>
        </tr>
      )}
    </>
  );
}
