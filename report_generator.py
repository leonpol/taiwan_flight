"""Generate daily Markdown digest and interactive HTML price-history dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import REPORTS_DIR
from providers.google_flights import build_google_flights_url


def _fmt_hm(minutes: int) -> str:
    h, m = divmod(max(0, int(minutes)), 60)
    return f"{h}h {m:02d}m"


def _enrich_with_gf_links(snapshot: dict[str, Any]) -> dict[str, Any]:
    for key in ("strict_matches", "watchlist_matches"):
        for it in snapshot.get(key, []):
            it["google_flights_url"] = build_google_flights_url(
                out_date=it["outbound_date"],
                in_date=it["inbound_date"],
                out_dest=it["taiwan_arrival_airport"],
                in_orig=it["taiwan_departure_airport"],
            )
    return snapshot


def generate_markdown_report(snapshot: dict[str, Any], reports_dir: Path = REPORTS_DIR) -> Path:
    """Write a crisp daily Markdown report to reports/latest.md and reports/YYYY-MM-DD.md."""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    _enrich_with_gf_links(snapshot)

    s = snapshot["summary"]
    sched = snapshot["schedule"]
    lines: list[str] = [
        f"# TLV ↔ Taiwan Flight Price Report — {snapshot['run_date']}",
        "",
        f"- **Checked at:** `{snapshot['checked_at_local']}` (`{sched['timezone']}`)",
        f"- **Daily Schedule:** `{sched['daily_time']}` (`{sched['timezone']}`)",
        f"- **Window:** Depart `TLV` **Oct 5–9, 2027** · Return from Taiwan (`TPE`/`TSA`/`KHH`/`RMQ`) **Oct 22–24, 2027** · 1 Adult Economy (`USD`)",
        f"- **Candidates Scanned:** `{s['raw_candidates_scanned']}` real itineraries → **{s['strict_total_count']} strict matches** (`{s['strict_ideal_count']}` ideal 2–4h, `{s['strict_acceptable_count']}` acceptable 4–6h / 8–10h / 18–20h) + `{s['watchlist_count']}` near-miss watchlist",
        f"- **Lowest Strict Fare Today:** `{('$' + str(s['min_strict_price_usd'])) if s['min_strict_price_usd'] else 'N/A'}` "
        f"(Ideal 2–4h: `{('$' + str(s['min_ideal_price_usd'])) if s['min_ideal_price_usd'] else 'N/A'}`)",
        "",
    ]

    gf_meta = (snapshot.get("providers") or {}).get("google_flights") or {}
    if gf_meta.get("horizon_note"):
        lines.append(f"> **Schedule Horizon Note:** {gf_meta['horizon_note']}")
        lines.append("")

    lines.append("## Top Strict Rule-Compliant Flights")
    lines.append("")
    strict = snapshot.get("strict_matches") or []
    if not strict:
        lines.append("_No strict rule-compliant flights found in this run._")
    else:
        lines.append("| # | Price (USD) | Dates | Taiwan Airports | Outbound Route & Layovers | Inbound Route & Layovers | Rules / Notes |")
        lines.append("|---:|---:|---|---|---|---|---|")
        for idx, it in enumerate(strict[:15], 1):
            delta = it.get("price_delta_usd")
            delta_str = f" ({'+' if delta > 0 else ''}${delta})" if delta else ""
            tw_pair = (
                it["taiwan_arrival_airport"]
                if not it["is_open_jaw_taiwan"]
                else f"{it['taiwan_arrival_airport']} → {it['taiwan_departure_airport']} (Open-Jaw)"
            )
            out_segs = " → ".join(
                [it["outbound"]["segments"][0]["origin_code"]]
                + [sg["dest_code"] for sg in it["outbound"]["segments"]]
            )
            out_lvs = ", ".join(f"{lv['arrival_airport']} {lv['duration_hours']:.1f}h" for lv in it["outbound_layovers"])
            in_segs = " → ".join(
                [it["inbound"]["segments"][0]["origin_code"]]
                + [sg["dest_code"] for sg in it["inbound"]["segments"]]
            )
            in_lvs = ", ".join(f"{lv['arrival_airport']} {lv['duration_hours']:.1f}h" for lv in it["inbound_layovers"])
            lines.append(
                f"| {idx} | **\\${it['price_usd']}**{delta_str} | {it['outbound_date']} → {it['inbound_date']} | "
                f"`{tw_pair}` | `{out_segs}` ({out_lvs or 'nonstop'}) | `{in_segs}` ({in_lvs or 'nonstop'}) | "
                f"{', '.join(it['badges'])} |"
            )

    watchlist = snapshot.get("watchlist_matches") or []
    if watchlist:
        lines.extend(["", "## Near-Miss Watchlist (±1.2h Layover Boundary)", ""])
        for it in watchlist[:8]:
            lines.append(
                f"- **\\${it['price_usd']}** (`{it['outbound_date']}` → `{it['inbound_date']}`, "
                f"`{it['taiwan_arrival_airport']}`/`{it['taiwan_departure_airport']}`): {it['summary_note']}"
            )

    content = "\n".join(lines) + "\n"
    latest_md = reports_dir / "latest.md"
    latest_md.write_text(content, encoding="utf-8")
    (reports_dir / f"report-{snapshot['run_date']}.md").write_text(content, encoding="utf-8")
    return latest_md


DASHBOARD_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TLV ↔ Taiwan Daily Flight Fare Monitor — Oct 2027</title>
  <meta name="description" content="Automated daily real-fare flight tracker for round-trip economy flights from Tel Aviv (TLV) to Taiwan (Oct 5–9 to Oct 22–24, 2027) with layover rule verification." />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg: hsl(40, 23%, 97%);
      --surface: hsl(0, 0%, 100%);
      --surface-subtle: hsl(38, 20%, 94%);
      --ink: hsl(215, 28%, 13%);
      --ink-secondary: hsl(215, 16%, 38%);
      --ink-muted: hsl(215, 12%, 54%);
      --border: hsl(35, 16%, 86%);
      --border-strong: hsl(35, 14%, 76%);
      --accent: hsl(196, 78%, 28%);
      --accent-soft: hsl(196, 55%, 93%);
      --teal: hsl(164, 68%, 26%);
      --teal-soft: hsl(164, 52%, 92%);
      --amber: hsl(32, 84%, 34%);
      --amber-soft: hsl(36, 85%, 93%);
      --danger: hsl(4, 70%, 42%);
      --shadow-sm: 0 1px 2px hsla(215, 28%, 13%, 0.04), 0 2px 8px hsla(215, 28%, 13%, 0.03);
      --radius: 10px;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }

    .mono {
      font-family: 'JetBrains Mono', monospace;
      font-variant-numeric: tabular-nums;
    }

    .shell {
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 24px 56px;
    }

    header.masthead {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: flex-end;
      gap: 16px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 22px;
    }

    h1 {
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.025em;
      margin: 0 0 4px;
    }

    .subtitle {
      color: var(--ink-secondary);
      margin: 0;
      font-size: 13.5px;
    }

    .masthead-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .schedule-tag {
      background: var(--surface);
      border: 1px solid var(--border);
      padding: 7px 12px;
      border-radius: 8px;
      font-size: 12.5px;
      color: var(--ink-secondary);
      box-shadow: var(--shadow-sm);
    }

    button.primary-btn {
      appearance: none;
      border: 1px solid var(--accent);
      background: var(--accent);
      color: #fff;
      font-family: inherit;
      font-weight: 600;
      font-size: 13px;
      padding: 8px 14px;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.15s ease, transform 0.1s ease;
    }
    button.primary-btn:hover { background: hsl(196, 78%, 23%); }
    button.primary-btn:active { transform: translateY(1px); }
    button.primary-btn:disabled { opacity: 0.6; cursor: wait; }

    .metrics-strip {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(205px, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }

    .metric-box {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 16px;
      box-shadow: var(--shadow-sm);
    }

    .metric-label {
      font-size: 12px;
      color: var(--ink-muted);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 4px;
    }

    .metric-value {
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--ink);
    }

    .metric-note {
      font-size: 12px;
      color: var(--ink-secondary);
      margin-top: 3px;
    }

    .notice-banner {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 12px 16px;
      margin-bottom: 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
      font-size: 13px;
      color: var(--ink-secondary);
    }

    .panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 18px 20px;
      margin-bottom: 20px;
      box-shadow: var(--shadow-sm);
    }

    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 14px;
    }

    h2 {
      font-size: 16px;
      font-weight: 700;
      letter-spacing: -0.015em;
      margin: 0;
    }

    .controls-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 14px;
    }

    .tab-btn {
      background: var(--surface-subtle);
      border: 1px solid transparent;
      color: var(--ink-secondary);
      font-family: inherit;
      font-size: 12.5px;
      font-weight: 600;
      padding: 6px 12px;
      border-radius: 7px;
      cursor: pointer;
      transition: all 0.14s ease;
    }
    .tab-btn:hover { color: var(--ink); border-color: var(--border-strong); }
    .tab-btn.active {
      background: var(--accent);
      color: #fff;
    }

    select.filter-select {
      font-family: inherit;
      font-size: 12.5px;
      padding: 6px 10px;
      border-radius: 7px;
      border: 1px solid var(--border-strong);
      background: var(--surface);
      color: var(--ink);
    }

    .flight-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .flight-row {
      border: 1px solid var(--border);
      border-radius: 9px;
      background: var(--surface);
      transition: border-color 0.15s ease;
    }
    .flight-row:hover { border-color: var(--border-strong); }

    .flight-summary {
      display: grid;
      grid-template-columns: 125px 1fr 1fr 175px;
      gap: 16px;
      align-items: center;
      padding: 14px 16px;
      cursor: pointer;
    }

    @media (max-width: 880px) {
      .flight-summary {
        grid-template-columns: 1fr;
        gap: 10px;
      }
    }

    .price-col .price {
      font-size: 21px;
      font-weight: 700;
      color: var(--ink);
    }

    .price-delta {
      font-size: 11.5px;
      font-weight: 600;
      margin-left: 5px;
    }
    .price-delta.down { color: var(--teal); }
    .price-delta.up { color: var(--danger); }

    .leg-block {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }

    .leg-topline {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      font-size: 13.5px;
    }

    .leg-subline {
      font-size: 12px;
      color: var(--ink-secondary);
    }

    .badge-wrap {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      justify-content: flex-end;
    }

    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 5px;
      font-size: 11.5px;
      font-weight: 600;
    }
    .badge.ideal { background: var(--teal-soft); color: var(--teal); }
    .badge.explore { background: var(--accent-soft); color: var(--accent); }
    .badge.warn { background: var(--amber-soft); color: var(--amber); }
    .badge.neutral { background: var(--surface-subtle); color: var(--ink-secondary); }

    .flight-details {
      display: none;
      border-top: 1px solid var(--border);
      background: hsl(40, 22%, 98.5%);
      padding: 14px 16px;
      font-size: 12.5px;
    }
    .flight-row.open .flight-details { display: block; }

    .details-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }
    @media (max-width: 780px) {
      .details-grid { grid-template-columns: 1fr; }
    }

    .seg-item {
      padding: 7px 0;
      border-bottom: 1px dashed var(--border);
    }
    .seg-item:last-child { border-bottom: none; }

    .layover-callout {
      margin: 6px 0;
      padding: 7px 10px;
      border-radius: 6px;
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--ink-secondary);
    }

    .detail-links {
      margin-top: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }

    a.action-link {
      display: inline-block;
      text-decoration: none;
      font-weight: 600;
      font-size: 12.5px;
      padding: 6px 12px;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
    }
    a.action-link.secondary {
      background: var(--surface);
      color: var(--accent);
      border: 1px solid var(--accent);
    }

    #trendCanvas {
      width: 100%;
      height: 190px;
      display: block;
    }

    .rules-footer {
      font-size: 12px;
      color: var(--ink-muted);
      margin-top: 22px;
      line-height: 1.6;
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="masthead">
      <div>
        <h1>TLV ↔ Taiwan Daily Flight Price Agent</h1>
        <p class="subtitle">
          1 Adult · Economy · Depart TLV <strong>Oct 5–9, 2027</strong> · Return from Taiwan (<span class="mono">TPE / TSA / KHH / RMQ</span>) <strong>Oct 22–24, 2027</strong> · No Persian Gulf / Turkey
        </p>
      </div>
      <div class="masthead-actions">
        <div class="schedule-tag" id="scheduleStatusBadge">
          Daily Check: <strong class="mono" id="schedTimeText">06:15 Asia/Jerusalem</strong>
        </div>
        <button id="runNowBtn" class="primary-btn" type="button" title="Trigger an immediate live price scan">
          Run Live Check Now
        </button>
      </div>
    </header>

    <section class="metrics-strip" aria-label="Daily fare summary">
      <div class="metric-box">
        <div class="metric-label">Best Strict Match</div>
        <div class="metric-value mono" id="metricMinStrict">—</div>
        <div class="metric-note" id="metricMinStrictSub">100% rule-compliant</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Best Ideal 2–4h Layover</div>
        <div class="metric-value mono" id="metricMinIdeal">—</div>
        <div class="metric-note">Single protected airline ticket</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Best Explore / 4–6h Option</div>
        <div class="metric-value mono" id="metricMinAcceptable">—</div>
        <div class="metric-note">8–10h city / 18–20h overnight / 4–6h</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Last Checked</div>
        <div class="metric-value mono" id="metricLastRun" style="font-size:16px; padding-top:4px;">—</div>
        <div class="metric-note" id="metricScannedCount">—</div>
      </div>
    </section>

    <div class="notice-banner" id="horizonNotice"></div>

    <section class="panel" aria-labelledby="historyHeading">
      <div class="panel-header">
        <h2 id="historyHeading">Daily Lowest Price History (USD)</h2>
        <span class="mono" style="font-size:12px; color:var(--ink-muted);" id="trendPointsCount"></span>
      </div>
      <canvas id="trendCanvas" width="1100" height="190"></canvas>
    </section>

    <main class="panel" aria-labelledby="itinerariesHeading">
      <div class="panel-header">
        <h2 id="itinerariesHeading">Verified Real Flight Itineraries</h2>
        <span style="font-size:12px; color:var(--ink-muted);">Click any row to inspect flight numbers, layover transit, luggage notes &amp; booking links</span>
      </div>

      <div class="controls-bar">
        <button class="tab-btn active" id="tabAllStrict" data-tab="ALL_STRICT" type="button">All Strict Matches</button>
        <button class="tab-btn" id="tabIdeal" data-tab="IDEAL" type="button">Ideal 2–4h</button>
        <button class="tab-btn" id="tabExplore" data-tab="EXPLORE" type="button">8–10h City &amp; 18–20h Overnight</button>
        <button class="tab-btn" id="tabShort46" data-tab="SHORT_4_6" type="button">4–6h Layover</button>
        <button class="tab-btn" id="tabWatchlist" data-tab="WATCHLIST" type="button">Near-Miss Watchlist</button>

        <select id="filterOutDate" class="filter-select" aria-label="Filter outbound departure date">
          <option value="">All Outbound Dates (Oct 5–9)</option>
          <option value="2027-10-05">Tue Oct 5, 2027</option>
          <option value="2027-10-06">Wed Oct 6, 2027</option>
          <option value="2027-10-07">Thu Oct 7, 2027</option>
          <option value="2027-10-08">Fri Oct 8, 2027</option>
          <option value="2027-10-09">Sat Oct 9, 2027</option>
        </select>

        <select id="filterInDate" class="filter-select" aria-label="Filter return departure date">
          <option value="">All Return Dates (Oct 22–24)</option>
          <option value="2027-10-22">Fri Oct 22, 2027</option>
          <option value="2027-10-23">Sat Oct 23, 2027</option>
          <option value="2027-10-24">Sun Oct 24, 2027</option>
        </select>

        <select id="filterTaiwanAirport" class="filter-select" aria-label="Filter Taiwan airport">
          <option value="">Any Taiwan Airport</option>
          <option value="TPE">TPE (Taipei Taoyuan)</option>
          <option value="TSA">TSA (Taipei Songshan)</option>
          <option value="KHH">KHH (Kaohsiung)</option>
          <option value="RMQ">RMQ (Taichung)</option>
          <option value="OPEN_JAW">Open-Jaw Taiwan Only</option>
        </select>
      </div>

      <div id="flightsContainer" class="flight-list"></div>
    </main>

    <footer class="rules-footer">
      <strong>Active Rule Engine:</strong>
      (1) Runs daily at 06:15 Asia/Jerusalem after overnight airline GDS batch updates ·
      (2) Zero Persian Gulf or Turkey stops/carriers ·
      (3) 2–4h single-ticket layovers preferred; 4–6h single-ticket layovers accepted &amp; benchmarked against 2–4h fares ·
      (4) 8–10h layovers accepted only at airports with left-luggage storage, ≤38m city rail transit, and ≥4.8h daytime city window ·
      (5) 18–20h overnight sleep+explore layovers accepted in Eastern Europe, Hong Kong, or Bangkok ·
      (6) Self-transfer permitted strictly on long layovers (8–10h or 18–20h), never on short connections.
    </footer>
  </div>

  <script id="embeddedReportData" type="application/json">__REPORT_JSON__</script>
  <script>
    let STATE = JSON.parse(document.getElementById('embeddedReportData').textContent);
    let activeTab = 'ALL_STRICT';

    function fmtUsd(v) {
      return v == null ? '—' : '$' + Number(v).toLocaleString('en-US');
    }

    function fmtHm(mins) {
      const h = Math.floor(mins / 60);
      const m = mins % 60;
      return `${h}h ${String(m).padStart(2, '0')}m`;
    }

    function fmtShortDt(iso) {
      if (!iso) return '';
      const d = iso.slice(5, 10);
      const t = iso.slice(11, 16);
      return `${d} ${t}`;
    }

    function badgeClass(text) {
      if (text.includes('Ideal') || text.includes('Single Airline') || text.includes('Good-Price')) return 'ideal';
      if (text.includes('Explore') || text.includes('Overnight') || text.includes('Open-Jaw')) return 'explore';
      if (text.includes('Self-Transfer') || text.includes('4–6h')) return 'warn';
      return 'neutral';
    }

    function renderMetrics() {
      const s = STATE.summary || {};
      document.getElementById('schedTimeText').textContent =
        `${STATE.schedule?.daily_time || '06:15'} ${STATE.schedule?.timezone || 'Asia/Jerusalem'}`;
      document.getElementById('metricMinStrict').textContent = fmtUsd(s.min_strict_price_usd);
      document.getElementById('metricMinStrictSub').textContent =
        `${s.strict_total_count || 0} strict matches found today`;
      document.getElementById('metricMinIdeal').textContent = fmtUsd(s.min_ideal_price_usd);
      document.getElementById('metricMinAcceptable').textContent = fmtUsd(s.min_acceptable_price_usd);
      document.getElementById('metricLastRun').textContent = (STATE.checked_at_local || '').slice(0, 16).replace('T', ' ');
      document.getElementById('metricScannedCount').textContent =
        `${s.raw_candidates_scanned || 0} real live candidates evaluated`;

      const gfNote = STATE.providers?.google_flights?.horizon_note || '';
      const kiwiCount = STATE.providers?.kiwi?.raw_candidates_fetched || 0;
      document.getElementById('horizonNotice').innerHTML = `
        <div><strong>Live Data Sources:</strong> Kiwi Umbrella GDS/Airline GraphQL (<span class="mono">${kiwiCount}</span> itineraries) + Google Flights Live Engine. ${gfNote}</div>
      `;
    }

    function drawTrendChart() {
      const canvas = document.getElementById('trendCanvas');
      const ctx = canvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);

      const w = rect.width;
      const h = rect.height;
      ctx.clearRect(0, 0, w, h);

      const trend = (STATE.daily_trend || []).filter(p => p.min_strict_price_usd != null);
      document.getElementById('trendPointsCount').textContent =
        `${trend.length} daily snapshot${trend.length === 1 ? '' : 's'}`;

      if (!trend.length) {
        ctx.fillStyle = '#6b7280';
        ctx.font = '13px Plus Jakarta Sans, sans-serif';
        ctx.fillText('No historical price points recorded yet.', 20, h / 2);
        return;
      }

      const padL = 62, padR = 28, padT = 22, padB = 34;
      const plotW = w - padL - padR;
      const plotH = h - padT - padB;

      const vals = [];
      trend.forEach(t => {
        if (t.min_strict_price_usd != null) vals.push(t.min_strict_price_usd);
        if (t.min_ideal_price_usd != null) vals.push(t.min_ideal_price_usd);
      });
      const minV = Math.floor(Math.min(...vals) * 0.92 / 50) * 50;
      const maxV = Math.ceil(Math.max(...vals) * 1.06 / 50) * 50 || (minV + 200);

      const xAt = i => trend.length === 1 ? padL + plotW / 2 : padL + (i / (trend.length - 1)) * plotW;
      const yAt = v => padT + plotH - ((v - minV) / Math.max(1, maxV - minV)) * plotH;

      ctx.strokeStyle = '#e5e0d8';
      ctx.lineWidth = 1;
      ctx.font = '11px JetBrains Mono, monospace';
      ctx.fillStyle = '#6e7785';
      for (let g = 0; g <= 3; g++) {
        const val = Math.round(minV + (g / 3) * (maxV - minV));
        const y = yAt(val);
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(w - padR, y);
        ctx.stroke();
        ctx.fillText('$' + val, 8, y + 4);
      }

      // Strict minimum line
      ctx.strokeStyle = '#0f5e7a';
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      trend.forEach((pt, idx) => {
        const x = xAt(idx), y = yAt(pt.min_strict_price_usd);
        if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();

      trend.forEach((pt, idx) => {
        const x = xAt(idx), y = yAt(pt.min_strict_price_usd);
        ctx.fillStyle = '#0f5e7a';
        ctx.beginPath();
        ctx.arc(x, y, 4.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#182230';
        ctx.font = '600 11.5px JetBrains Mono, monospace';
        ctx.fillText('$' + pt.min_strict_price_usd, x - 18, y - 10);

        if (trend.length <= 12 || idx % Math.ceil(trend.length / 10) === 0 || idx === trend.length - 1) {
          ctx.fillStyle = '#6e7785';
          ctx.font = '11px JetBrains Mono, monospace';
          ctx.fillText(pt.run_date.slice(5), x - 16, h - 10);
        }
      });
    }

    function renderSectorDetail(title, sector, layovers) {
      let html = `<div style="font-weight:700; margin-bottom:6px;">${title} · Total ${fmtHm(sector.total_duration_minutes)}</div>`;
      sector.segments.forEach((seg, idx) => {
        if (idx > 0 && layovers[idx - 1]) {
          const lv = layovers[idx - 1];
          html += `<div class="layover-callout">
            <strong>Layover at ${lv.arrival_airport} (${lv.city || lv.arrival_airport}): ${lv.duration_hours.toFixed(1)}h</strong>
            ${lv.is_self_transfer ? ' · <span style="color:var(--amber);font-weight:600;">Self-Transfer</span>' : ' · Protected Connection'}
            <div style="margin-top:2px;">${lv.reason}${lv.transit_summary ? ' · ' + lv.transit_summary : ''}${lv.luggage_note ? ' · ' + lv.luggage_note : ''}</div>
          </div>`;
        }
        html += `<div class="seg-item">
          <div><strong class="mono">${seg.carrier_code}${seg.flight_number}</strong> (${seg.carrier_name || seg.carrier_code}) · ${fmtHm(seg.duration_minutes)}</div>
          <div class="mono" style="color:var(--ink-secondary); margin-top:2px;">
            ${seg.origin_code} ${fmtShortDt(seg.departure_local)} → ${seg.dest_code} ${fmtShortDt(seg.arrival_local)}
          </div>
        </div>`;
      });
      return html;
    }

    function filterItineraries() {
      const outFilter = document.getElementById('filterOutDate').value;
      const inFilter = document.getElementById('filterInDate').value;
      const twFilter = document.getElementById('filterTaiwanAirport').value;

      let pool = activeTab === 'WATCHLIST'
        ? (STATE.watchlist_matches || [])
        : (STATE.strict_matches || []);

      return pool.filter(it => {
        const lvs = [...(it.outbound_layovers || []), ...(it.inbound_layovers || [])];
        if (activeTab === 'IDEAL' && it.tier !== 'STRICT_IDEAL') return false;
        if (activeTab === 'EXPLORE' && !lvs.some(l => l.category === 'DAY_EXPLORE_8_10H' || l.category === 'OVERNIGHT_EXPLORE_18_20H')) return false;
        if (activeTab === 'SHORT_4_6' && !lvs.some(l => l.category === 'ACCEPTABLE_SHORT_4_6H')) return false;

        if (outFilter && it.outbound_date !== outFilter) return false;
        if (inFilter && it.inbound_date !== inFilter) return false;
        if (twFilter === 'OPEN_JAW' && !it.is_open_jaw_taiwan) return false;
        if (twFilter && twFilter !== 'OPEN_JAW' && it.taiwan_arrival_airport !== twFilter && it.taiwan_departure_airport !== twFilter) return false;
        return true;
      });
    }

    function renderFlights() {
      const container = document.getElementById('flightsContainer');
      const items = filterItineraries();
      if (!items.length) {
        container.innerHTML = `<div style="padding:26px; text-align:center; color:var(--ink-muted);">
          No itineraries match the currently selected filter combination today. Try switching tabs or clearing date filters.
        </div>`;
        return;
      }

      container.innerHTML = items.map((it, idx) => {
        const outChain = [it.outbound.segments[0].origin_code, ...it.outbound.segments.map(s => s.dest_code)].join(' → ');
        const inChain = [it.inbound.segments[0].origin_code, ...it.inbound.segments.map(s => s.dest_code)].join(' → ');
        const outLvText = (it.outbound_layovers || []).map(l => `${l.arrival_airport} ${l.duration_hours.toFixed(1)}h`).join(', ') || 'Direct';
        const inLvText = (it.inbound_layovers || []).map(l => `${l.arrival_airport} ${l.duration_hours.toFixed(1)}h`).join(', ') || 'Direct';

        let deltaHtml = '';
        if (it.price_delta_usd != null && it.price_delta_usd !== 0) {
          const cls = it.price_delta_usd < 0 ? 'down' : 'up';
          const sign = it.price_delta_usd > 0 ? '+' : '';
          deltaHtml = `<span class="price-delta mono ${cls}">${sign}$${it.price_delta_usd}</span>`;
        }

        const badgesHtml = (it.badges || []).map(b => `<span class="badge ${badgeClass(b)}">${b}</span>`).join('');

        let linksHtml = '';
        if (it.booking_url && !it.inbound_booking_url) {
          linksHtml += `<a class="action-link" href="${it.booking_url}" target="_blank" rel="noopener">View Live Booking Offer</a>`;
        } else if (it.booking_url && it.inbound_booking_url) {
          linksHtml += `<a class="action-link" href="${it.booking_url}" target="_blank" rel="noopener">Book Outbound Leg</a>`;
          linksHtml += `<a class="action-link" href="${it.inbound_booking_url}" target="_blank" rel="noopener">Book Inbound Leg</a>`;
        }
        if (it.google_flights_url) {
          linksHtml += `<a class="action-link secondary" href="${it.google_flights_url}" target="_blank" rel="noopener">Compare on Google Flights</a>`;
        }

        return `
          <article class="flight-row" id="flightRow_${idx}">
            <div class="flight-summary" onclick="document.getElementById('flightRow_${idx}').classList.toggle('open')">
              <div class="price-col">
                <span class="price mono">${fmtUsd(it.price_usd)}</span>${deltaHtml}
                <div style="font-size:11.5px; color:var(--ink-muted);">${it.pnr_count === 1 ? '1 Ticket (PNR)' : it.pnr_count + ' Tickets'}</div>
              </div>
              <div class="leg-block">
                <div class="leg-topline"><span class="mono">${outChain}</span></div>
                <div class="leg-subline mono">${fmtShortDt(it.outbound.segments[0].departure_local)} → ${fmtShortDt(it.outbound.segments[it.outbound.segments.length-1].arrival_local)} · ${fmtHm(it.outbound.total_duration_minutes)} (${outLvText})</div>
              </div>
              <div class="leg-block">
                <div class="leg-topline"><span class="mono">${inChain}</span></div>
                <div class="leg-subline mono">${fmtShortDt(it.inbound.segments[0].departure_local)} → ${fmtShortDt(it.inbound.segments[it.inbound.segments.length-1].arrival_local)} · ${fmtHm(it.inbound.total_duration_minutes)} (${inLvText})</div>
              </div>
              <div class="badge-wrap">${badgesHtml}</div>
            </div>
            <div class="flight-details">
              <div class="details-grid">
                <div>${renderSectorDetail('Outbound (TLV → Taiwan)', it.outbound, it.outbound_layovers || [])}</div>
                <div>${renderSectorDetail('Return (Taiwan → TLV)', it.inbound, it.inbound_layovers || [])}</div>
              </div>
              <div style="margin-top:10px; color:var(--ink-secondary);"><strong>Rule Assessment:</strong> ${it.summary_note}</div>
              <div class="detail-links">${linksHtml}</div>
            </div>
          </article>
        `;
      }).join('');
    }

    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        activeTab = btn.dataset.tab;
        renderFlights();
      });
    });

    ['filterOutDate', 'filterInDate', 'filterTaiwanAirport'].forEach(id => {
      document.getElementById(id).addEventListener('change', renderFlights);
    });

    document.getElementById('runNowBtn').addEventListener('click', async () => {
      const btn = document.getElementById('runNowBtn');
      btn.disabled = true;
      btn.textContent = 'Scanning Live Fares...';
      try {
        const res = await fetch('/api/run-check', { method: 'POST' });
        if (!res.ok) throw new Error('Daemon endpoint unavailable in static file mode');
        STATE = await res.json();
        renderMetrics();
        drawTrendChart();
        renderFlights();
        btn.textContent = 'Updated Just Now';
        setTimeout(() => { btn.textContent = 'Run Live Check Now'; btn.disabled = false; }, 2200);
      } catch (err) {
        alert('Live re-scan requires opening via the running agent server (agent.py --daemon). Showing embedded snapshot.');
        btn.textContent = 'Run Live Check Now';
        btn.disabled = false;
      }
    });

    window.addEventListener('resize', drawTrendChart);
    renderMetrics();
    drawTrendChart();
    renderFlights();
  </script>
</body>
</html>
"""


def generate_html_dashboard(snapshot: dict[str, Any], reports_dir: Path = REPORTS_DIR) -> Path:
    """Render standalone interactive HTML dashboard to reports/dashboard.html."""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    _enrich_with_gf_links(snapshot)

    safe_json = json.dumps(snapshot).replace("</", "<\\/")
    html = DASHBOARD_TEMPLATE.replace("__REPORT_JSON__", safe_json)
    out_path = reports_dir / "dashboard.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
