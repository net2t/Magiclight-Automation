"""
dashboard.py — MagicLight Auto v3.0
======================================
Flask monitoring dashboard for the video pipeline.

Run standalone:
    python dashboard.py

Routes:
    GET  /              → Dashboard HTML
    GET  /api/videos    → JSON feed of all sheet rows
    POST /api/retry/<row>           → Mark row as PENDING (triggers re-generation)
    POST /api/force-process/<row>   → Trigger local FFmpeg re-process for a row

The dashboard reads status directly from Google Sheets for accuracy.
Auto-refreshes every 30 seconds via JavaScript.
"""

import os
import json
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, render_template_string

from config import (
    DASHBOARD_PORT, DASHBOARD_HOST, DASHBOARD_SECRET_KEY, OUT_BASE, log
)

app = Flask(__name__)
app.secret_key = DASHBOARD_SECRET_KEY

# ── Status colour map ─────────────────────────────────────────────────────────
STATUS_COLOURS = {
    "pending":    "#6c757d",
    "processing": "#0d6efd",
    "generated":  "#198754",
    "processed":  "#0dcaf0",
    "uploaded":   "#ffc107",
    "done":       "#ffc107",
    "error":      "#dc3545",
    "low credit": "#fd7e14",
    "no_video":   "#6f42c1",
}

# ── HTML template ─────────────────────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="MagicLight Auto Pipeline Dashboard — real-time video status monitor">
<title>MagicLight Dashboard</title>
<style>
  :root {
    --bg: #0f1117; --card: #1a1d27; --border: #2a2d3e;
    --text: #e2e8f0; --muted: #64748b; --accent: #6366f1;
    --green: #22c55e; --red: #ef4444; --yellow: #f59e0b;
    --blue: #3b82f6; --teal: #06b6d4; --orange: #f97316;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Inter', system-ui, sans-serif;
         font-size: 14px; min-height: 100vh; }
  .topbar { background: var(--card); border-bottom: 1px solid var(--border);
             padding: 14px 24px; display: flex; align-items: center; gap: 16px;
             position: sticky; top: 0; z-index: 100; }
  .topbar h1 { font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }
  .topbar h1 span { color: var(--accent); }
  .badge { background: var(--accent); color: #fff; font-size: 11px; padding: 2px 8px;
           border-radius: 99px; font-weight: 600; }
  .refresh-info { margin-left: auto; color: var(--muted); font-size: 12px; }
  .stats-row { display: flex; gap: 12px; padding: 20px 24px 0; flex-wrap: wrap; }
  .stat-card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
               padding: 14px 20px; min-width: 130px; flex: 1; }
  .stat-card .val { font-size: 28px; font-weight: 700; line-height: 1; }
  .stat-card .lbl { color: var(--muted); font-size: 12px; margin-top: 4px; }
  .container { padding: 20px 24px; }
  .search-row { display: flex; gap: 10px; margin-bottom: 14px; }
  .search-row input { background: var(--card); border: 1px solid var(--border); color: var(--text);
                       padding: 8px 14px; border-radius: 8px; flex: 1; font-size: 13px;
                       outline: none; transition: border-color .2s; }
  .search-row input:focus { border-color: var(--accent); }
  .search-row select { background: var(--card); border: 1px solid var(--border); color: var(--text);
                        padding: 8px 12px; border-radius: 8px; font-size: 13px; outline: none; cursor: pointer; }
  table { width: 100%; border-collapse: collapse; background: var(--card);
           border-radius: 12px; overflow: hidden; border: 1px solid var(--border); }
  thead th { padding: 12px 14px; text-align: left; font-size: 11px; text-transform: uppercase;
              letter-spacing: .6px; color: var(--muted); border-bottom: 1px solid var(--border); }
  tbody tr { border-bottom: 1px solid var(--border); transition: background .15s; }
  tbody tr:last-child { border-bottom: none; }
  tbody tr:hover { background: rgba(255,255,255,.03); }
  tbody td { padding: 11px 14px; vertical-align: middle; }
  .status-pill { display: inline-block; padding: 3px 10px; border-radius: 99px;
                  font-size: 11px; font-weight: 600; text-transform: uppercase; }
  a.yt-link { color: #ff0000; text-decoration: none; font-weight: 600; font-size: 12px; }
  a.yt-link:hover { text-decoration: underline; }
  .actions { display: flex; gap: 6px; }
  .btn { padding: 5px 12px; border: none; border-radius: 6px; font-size: 12px; font-weight: 600;
          cursor: pointer; transition: opacity .2s; }
  .btn:hover { opacity: .8; }
  .btn-retry  { background: #e4512022; color: #f97316; border: 1px solid #f97316; }
  .btn-proc   { background: #0d6efd22; color: #3b82f6; border: 1px solid #3b82f6; }
  .empty-state { text-align: center; padding: 60px 20px; color: var(--muted); }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--border);
              border-top-color: var(--accent); border-radius: 50%; animation: spin 0.7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .toast { position: fixed; bottom: 24px; right: 24px; background: var(--card);
            border: 1px solid var(--border); border-radius: 10px; padding: 12px 18px;
            font-size: 13px; opacity: 0; transition: opacity .3s; pointer-events: none; z-index: 9999; }
  .toast.show { opacity: 1; }
  @media (max-width: 768px) {
    .stats-row { gap: 8px; }
    thead th:nth-child(n+4) { display: none; }
    tbody td:nth-child(n+4) { display: none; }
  }
</style>
</head>
<body>
<div class="topbar">
  <h1>Magic<span>Light</span> Dashboard</h1>
  <span class="badge" id="version-badge">v3.0</span>
  <span class="refresh-info">Auto-refresh in <span id="countdown">30</span>s
    &nbsp;|&nbsp; Last updated: <span id="last-updated">—</span>
    &nbsp;<span id="spinner" class="spinner" style="display:none"></span>
  </span>
</div>

<div class="stats-row" id="stats-row">
  <div class="stat-card"><div class="val" id="s-total">—</div><div class="lbl">Total</div></div>
  <div class="stat-card"><div class="val" style="color:var(--muted)" id="s-pending">—</div><div class="lbl">Pending</div></div>
  <div class="stat-card"><div class="val" style="color:var(--blue)" id="s-processing">—</div><div class="lbl">Processing</div></div>
  <div class="stat-card"><div class="val" style="color:var(--green)" id="s-generated">—</div><div class="lbl">Generated</div></div>
  <div class="stat-card"><div class="val" style="color:var(--teal)" id="s-processed">—</div><div class="lbl">Processed</div></div>
  <div class="stat-card"><div class="val" style="color:var(--yellow)" id="s-uploaded">—</div><div class="lbl">Uploaded</div></div>
  <div class="stat-card"><div class="val" style="color:var(--red)" id="s-error">—</div><div class="lbl">Errors</div></div>
</div>

<div class="container">
  <div class="search-row">
    <input type="text" id="search-input" placeholder="Search title, status, email…" oninput="filterTable()">
    <select id="status-filter" onchange="filterTable()">
      <option value="">All Statuses</option>
      <option>Pending</option><option>Processing</option><option>Generated</option>
      <option>Processed</option><option>Uploaded</option><option>Done</option><option>Error</option>
    </select>
    <button class="btn btn-retry" onclick="loadVideos()">↻ Refresh</button>
  </div>
  <table id="main-table">
    <thead>
      <tr>
        <th>#</th><th>Title</th><th>Status</th><th>YouTube</th>
        <th>Email</th><th>Updated</th><th>Actions</th>
      </tr>
    </thead>
    <tbody id="table-body">
      <tr><td colspan="7" class="empty-state">Loading…</td></tr>
    </tbody>
  </table>
</div>

<div class="toast" id="toast"></div>

<script>
const COLOURS = {{ colours|safe }};
let allRows = [];
let countdown = 30;
let timer;

function statusColour(status) {
  const k = (status || '').toLowerCase();
  return COLOURS[k] || '#6c757d';
}

function pill(status) {
  const c = statusColour(status);
  return `<span class="status-pill" style="background:${c}22;color:${c};border:1px solid ${c}">${status}</span>`;
}

function showToast(msg, ok=true) {
  const t = document.getElementById('toast');
  t.textContent = (ok ? '✅ ' : '❌ ') + msg;
  t.style.borderColor = ok ? 'var(--green)' : 'var(--red)';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

function renderTable(rows) {
  const tbody = document.getElementById('table-body');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No rows found.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(r => {
    const ytLink = r.YouTube_URL
      ? `<a class="yt-link" href="${r.YouTube_URL}" target="_blank" rel="noopener">▶ Watch</a>`
      : '<span style="color:var(--muted)">—</span>';
    return `<tr>
      <td>${r._row}</td>
      <td>${(r.Title || '').substring(0,45)}</td>
      <td>${pill(r.Status || '—')}</td>
      <td>${ytLink}</td>
      <td style="color:var(--muted);font-size:12px">${(r.Email_Used || '').substring(0,28)}</td>
      <td style="color:var(--muted);font-size:12px">${r.Completed_Time || r.Created_Time || ''}</td>
      <td>
        <div class="actions">
          <button class="btn btn-retry" onclick="retryRow(${r._row})" title="Reset to Pending">↺ Retry</button>
          <button class="btn btn-proc"  onclick="forceProcess(${r._row})" title="Force local re-process">⚙ Process</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

function updateStats(rows) {
  const cnt = s => rows.filter(r => (r.Status||'').toLowerCase() === s).length;
  document.getElementById('s-total').textContent      = rows.length;
  document.getElementById('s-pending').textContent    = cnt('pending');
  document.getElementById('s-processing').textContent = cnt('processing');
  document.getElementById('s-generated').textContent  = cnt('generated');
  document.getElementById('s-processed').textContent  = cnt('processed');
  document.getElementById('s-uploaded').textContent   = rows.filter(r => ['uploaded','done'].includes((r.Status||'').toLowerCase())).length;
  document.getElementById('s-error').textContent      = cnt('error');
}

function filterTable() {
  const q  = document.getElementById('search-input').value.toLowerCase();
  const st = document.getElementById('status-filter').value.toLowerCase();
  const filtered = allRows.filter(r => {
    const match = !q || JSON.stringify(r).toLowerCase().includes(q);
    const matchS = !st || (r.Status||'').toLowerCase() === st;
    return match && matchS;
  });
  renderTable(filtered);
}

async function loadVideos() {
  document.getElementById('spinner').style.display = 'inline-block';
  try {
    const res  = await fetch('/api/videos');
    const data = await res.json();
    allRows = data.videos || [];
    updateStats(allRows);
    filterTable();
    document.getElementById('last-updated').textContent = new Date().toLocaleTimeString();
  } catch(e) {
    showToast('Failed to load data: ' + e.message, false);
  } finally {
    document.getElementById('spinner').style.display = 'none';
  }
}

async function retryRow(row) {
  try {
    const res = await fetch(`/api/retry/${row}`, {method:'POST'});
    const d   = await res.json();
    showToast(d.message || 'Row reset to Pending', d.ok);
    if (d.ok) setTimeout(loadVideos, 800);
  } catch(e) { showToast('Error: ' + e.message, false); }
}

async function forceProcess(row) {
  try {
    const res = await fetch(`/api/force-process/${row}`, {method:'POST'});
    const d   = await res.json();
    showToast(d.message || 'Processing triggered', d.ok);
    if (d.ok) setTimeout(loadVideos, 2000);
  } catch(e) { showToast('Error: ' + e.message, false); }
}

function startCountdown() {
  clearInterval(timer);
  countdown = 30;
  timer = setInterval(() => {
    countdown--;
    document.getElementById('countdown').textContent = countdown;
    if (countdown <= 0) { loadVideos(); countdown = 30; }
  }, 1000);
}

loadVideos();
startCountdown();
</script>
</body>
</html>"""


# ── Helper: sheet cache ───────────────────────────────────────────────────────
_cache_lock = threading.Lock()
_cache = {"data": [], "ts": 0.0}
CACHE_TTL = 30  # seconds


def _get_data(force: bool = False) -> list[dict]:
    with _cache_lock:
        if force or (datetime.now().timestamp() - _cache["ts"] > CACHE_TTL):
            try:
                from sheets import read_sheet
                rows = read_sheet()
                for i, r in enumerate(rows, start=2):
                    r["_row"] = i
                _cache["data"] = rows
                _cache["ts"]   = datetime.now().timestamp()
            except Exception as e:
                log.warning(f"[dashboard] Sheet read failed: {e}")
        return _cache["data"]


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    import json as _json
    colours_json = _json.dumps(STATUS_COLOURS)
    return render_template_string(DASHBOARD_HTML, colours=colours_json)


@app.route("/api/videos")
def api_videos():
    rows = _get_data(force=request.args.get("refresh") == "1")
    return jsonify({"videos": rows, "count": len(rows),
                    "ts": datetime.now().isoformat()})


@app.route("/api/retry/<int:row_num>", methods=["POST"])
def api_retry(row_num: int):
    try:
        from sheets import update_sheet_row
        update_sheet_row(row_num, Status="Pending",
                         Notes=f"Manual retry via dashboard at {datetime.now().strftime('%H:%M:%S')}")
        _get_data(force=True)
        return jsonify({"ok": True, "message": f"Row {row_num} reset to Pending"})
    except Exception as e:
        log.error(f"[dashboard] Retry failed for row {row_num}: {e}")
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/force-process/<int:row_num>", methods=["POST"])
def api_force_process(row_num: int):
    """
    Trigger local FFmpeg re-process for a specific row.
    Looks for raw video in output/ matching row number.
    """
    def _run():
        try:
            from pathlib import Path
            from processor import scan_videos, process_video
            from sheets import update_sheet_row

            update_sheet_row(row_num, Status="Processing",
                             Notes=f"Force-process via dashboard at {datetime.now().strftime('%H:%M:%S')}")
            base = Path(OUT_BASE)
            all_vids = scan_videos(base)
            target = [v for v in all_vids if f"R{row_num}_" in v.stem]
            if not target:
                update_sheet_row(row_num, Status="Error",
                                 Notes=f"Force-process: video file not found for R{row_num}")
                return
            success, out_path = process_video(target[0])
            if success and out_path:
                update_sheet_row(row_num, Status="Processed",
                                 Notes=f"Force-processed: {out_path.name}",
                                 Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            else:
                update_sheet_row(row_num, Status="Error",
                                 Notes="Force-process: FFmpeg failed")
        except Exception as e:
            log.error(f"[dashboard] Force-process thread error: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": f"Processing triggered for row {row_num} (runs in background)"})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "ts": datetime.now().isoformat()})


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info(f"[dashboard] Starting on http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False, threaded=True)
