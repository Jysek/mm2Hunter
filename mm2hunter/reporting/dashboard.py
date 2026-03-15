"""
Lightweight web dashboard served with aiohttp.

Displays discovered MM2 shops that passed validation in a clean table,
with live stats and the ability to download CSV/JSON exports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aiohttp import web

from mm2hunter.config import DashboardConfig
from mm2hunter.utils.logging import get_logger

logger = get_logger("dashboard")

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MM2 Shop Discovery &mdash; Dashboard</title>
<style>
  :root {{ --bg:#0f1117; --card:#1a1d27; --accent:#6c63ff; --green:#00e676;
          --red:#ff5252; --txt:#e0e0e0; --muted:#888; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg);
         color:var(--txt); padding:2rem; }}
  h1 {{ color:var(--accent); margin-bottom:.25rem; font-size:1.8rem; }}
  .subtitle {{ color:var(--muted); margin-bottom:1.5rem; font-size:.95rem; }}
  .stats {{ display:flex; gap:1rem; flex-wrap:wrap; margin-bottom:1.5rem; }}
  .stat {{ background:var(--card); border-radius:10px; padding:1rem 1.5rem;
          min-width:130px; text-align:center; }}
  .stat .num {{ font-size:2rem; font-weight:700; }}
  .stat .lbl {{ color:var(--muted); font-size:.75rem; text-transform:uppercase; }}
  table {{ width:100%; border-collapse:collapse; margin-top:1rem; }}
  th, td {{ padding:.65rem 1rem; text-align:left; border-bottom:1px solid #2a2d3a; }}
  th {{ background:var(--card); color:var(--accent); font-size:.8rem;
       text-transform:uppercase; letter-spacing:.04em; position:sticky; top:0; }}
  tr:hover {{ background:#1e2130; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:4px;
           font-size:.75rem; font-weight:600; }}
  .badge.pass {{ background:var(--green); color:#000; }}
  .badge.fail {{ background:var(--red); color:#fff; }}
  .badge.yes  {{ background:#1b5e20; color:var(--green); }}
  .badge.no   {{ background:#b71c1c33; color:var(--red); }}
  .badge.fast {{ background:#1565c0; color:#90caf9; }}
  .badge.deep {{ background:#6a1b9a; color:#ce93d8; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .actions {{ margin-bottom:1.5rem; }}
  .btn {{ display:inline-block; padding:.5rem 1.2rem; border-radius:6px;
         background:var(--accent); color:#fff; font-weight:600;
         text-decoration:none; margin-right:.5rem; font-size:.85rem; }}
  .btn:hover {{ opacity:.85; }}
  .empty {{ text-align:center; padding:3rem; color:var(--muted); }}
  .url-list {{ background:var(--card); border-radius:10px; padding:1rem 1.5rem;
              max-height:300px; overflow-y:auto; font-family:monospace;
              font-size:.85rem; line-height:1.8; }}
  .url-list a {{ display:block; }}
  .tab-bar {{ display:flex; gap:0; margin-bottom:0; }}
  .tab {{ padding:.6rem 1.5rem; background:var(--card); color:var(--muted);
         cursor:pointer; border:none; font-size:.9rem; font-weight:600;
         border-radius:8px 8px 0 0; }}
  .tab.active {{ background:var(--accent); color:#fff; }}
  .tab-content {{ display:none; }}
  .tab-content.active {{ display:block; }}
</style>
</head>
<body>
<h1>MM2 Shop Discovery Tool</h1>
<p class="subtitle">Automated Roblox Murder Mystery 2 shop finder &amp; validator &mdash; v2.0</p>

<div class="stats">
  <div class="stat"><div class="num">{total_scanned}</div><div class="lbl">Scanned</div></div>
  <div class="stat"><div class="num" style="color:var(--green)">{total_passed}</div><div class="lbl">Passed</div></div>
  <div class="stat"><div class="num" style="color:var(--red)">{total_failed}</div><div class="lbl">Failed</div></div>
  <div class="stat"><div class="num">{stripe_detected}</div><div class="lbl">Stripe</div></div>
  <div class="stat"><div class="num">{wallet_detected}</div><div class="lbl">Wallet</div></div>
  <div class="stat"><div class="num">{harvester_found}</div><div class="lbl">Harvester</div></div>
  <div class="stat"><div class="num">{total_discovered}</div><div class="lbl">Discovered</div></div>
  <div class="stat"><div class="num">{fast_scanned}</div><div class="lbl">Fast Scan</div></div>
  <div class="stat"><div class="num">{deep_scanned}</div><div class="lbl">Deep Scan</div></div>
</div>

<div class="actions">
  <a class="btn" href="/api/results?format=json" download="mm2_results.json">Download JSON</a>
  <a class="btn" href="/api/results?format=csv" download="mm2_results.csv">Download CSV</a>
  <a class="btn" href="/api/discovered" download="discovered_urls.txt">Download Discovered URLs</a>
</div>

<div class="tab-bar">
  <button class="tab active" onclick="switchTab('validated')">Validated Results</button>
  <button class="tab" onclick="switchTab('discovered')">Discovered URLs (pre-validation)</button>
</div>

<div id="tab-validated" class="tab-content active">
{table_html}
</div>

<div id="tab-discovered" class="tab-content">
{discovered_html}
</div>

<p class="subtitle" style="margin-top:2rem;">Generated: {generated_at}</p>

<script>
function switchTab(name) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}}
</script>
</body>
</html>
"""

ROW_TEMPLATE = """\
<tr>
  <td><a href="{url}" target="_blank" rel="noopener">{url_short}</a></td>
  <td><span class="badge {stripe_cls}">{stripe_txt}</span></td>
  <td><span class="badge {wallet_cls}">{wallet_txt}</span></td>
  <td>{harvester_price}</td>
  <td><span class="badge {stock_cls}">{stock_txt}</span></td>
  <td><span class="badge {status_cls}">{status_txt}</span></td>
  <td><span class="badge {scan_cls}">{scan_txt}</span></td>
  <td>{discovered_at}</td>
</tr>"""


def _build_table(results: list[dict]) -> str:
    if not results:
        return '<div class="empty">No validated results yet. Run a search first.</div>'
    rows = []
    for r in results:
        price = r.get("harvester_price")
        scan = r.get("scan_mode", "fast")
        rows.append(ROW_TEMPLATE.format(
            url=r["url"],
            url_short=r["url"][:55] + ("..." if len(r["url"]) > 55 else ""),
            stripe_cls="yes" if r["has_stripe"] else "no",
            stripe_txt="Yes" if r["has_stripe"] else "No",
            wallet_cls="yes" if r["has_wallet"] else "no",
            wallet_txt="Yes" if r["has_wallet"] else "No",
            harvester_price=f"${price:.2f}" if price is not None else "N/A",
            stock_cls="yes" if r["harvester_in_stock"] else "no",
            stock_txt="In Stock" if r["harvester_in_stock"] else "N/A",
            status_cls="pass" if r["passed"] else "fail",
            status_txt="PASS" if r["passed"] else "FAIL",
            scan_cls=scan,
            scan_txt=scan.upper(),
            discovered_at=r.get("discovered_at", "")[:19],
        ))
    header = (
        "<table><thead><tr>"
        "<th>URL</th><th>Stripe</th><th>Wallet</th>"
        "<th>Price</th><th>Stock</th><th>Status</th><th>Scan</th><th>Discovered</th>"
        "</tr></thead><tbody>"
    )
    return header + "\n".join(rows) + "</tbody></table>"


def _build_discovered_html(urls: list[str]) -> str:
    """Build the discovered URLs panel."""
    if not urls:
        return '<div class="empty">No discovered URLs yet. Run a search first.</div>'
    links = "\n".join(
        f'<a href="{u}" target="_blank" rel="noopener">{u}</a>' for u in urls
    )
    return f'<div class="url-list">{links}</div>'


# ---------------------------------------------------------------------------
# aiohttp application
# ---------------------------------------------------------------------------

class Dashboard:
    """Serves the MM2 discovery dashboard."""

    def __init__(self, config: DashboardConfig, data_dir: Path) -> None:
        self._cfg = config
        self._data_dir = data_dir
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/results", self._handle_api_results)
        self._app.router.add_get("/api/stats", self._handle_api_stats)
        self._app.router.add_get("/api/discovered", self._handle_api_discovered)
        self._runner: web.AppRunner | None = None

    def _load_results(self) -> list[dict]:
        json_path = self._data_dir / "results.json"
        if not json_path.exists():
            return []
        try:
            with open(json_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load results.json: %s", exc)
            return []

    def _load_stats(self) -> dict[str, Any]:
        stats_path = self._data_dir / "stats.json"
        if stats_path.exists():
            try:
                with open(stats_path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "total_scanned": 0, "total_passed": 0, "total_failed": 0,
            "stripe_detected": 0, "wallet_detected": 0, "harvester_found": 0,
            "fast_scanned": 0, "deep_scanned": 0,
            "generated_at": "---",
        }

    def _load_discovered_urls(self) -> list[str]:
        txt_path = self._data_dir / "discovered_urls.txt"
        if not txt_path.exists():
            return []
        try:
            with open(txt_path, encoding="utf-8") as fh:
                return [line.strip() for line in fh if line.strip()]
        except OSError:
            return []

    async def _handle_index(self, request: web.Request) -> web.Response:
        results = self._load_results()
        stats = self._load_stats()
        discovered = self._load_discovered_urls()

        table_html = _build_table(results)
        discovered_html = _build_discovered_html(discovered)

        html = HTML_TEMPLATE.format(
            table_html=table_html,
            discovered_html=discovered_html,
            total_discovered=len(discovered),
            **stats,
        )
        return web.Response(text=html, content_type="text/html")

    async def _handle_api_results(self, request: web.Request) -> web.Response:
        fmt = request.query.get("format", "json")
        if fmt == "csv":
            csv_path = self._data_dir / "results.csv"
            if csv_path.exists():
                return web.FileResponse(csv_path, headers={
                    "Content-Disposition": "attachment; filename=mm2_results.csv"
                })
            return web.Response(text="No CSV available yet.", status=404)
        results = self._load_results()
        return web.json_response(results)

    async def _handle_api_stats(self, request: web.Request) -> web.Response:
        return web.json_response(self._load_stats())

    async def _handle_api_discovered(self, request: web.Request) -> web.Response:
        txt_path = self._data_dir / "discovered_urls.txt"
        if txt_path.exists():
            return web.FileResponse(txt_path, headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Content-Disposition": "attachment; filename=discovered_urls.txt",
            })
        return web.Response(text="No discovered URLs file yet.", status=404)

    async def start(self) -> None:
        """Start the aiohttp web server."""
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._cfg.host, self._cfg.port)
        await site.start()
        logger.info(
            "Dashboard running at http://%s:%s", self._cfg.host, self._cfg.port,
        )

    async def stop(self) -> None:
        """Gracefully stop the dashboard."""
        if self._runner:
            await self._runner.cleanup()
