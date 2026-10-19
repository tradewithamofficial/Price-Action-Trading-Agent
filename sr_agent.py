"""Reusable S/R requests and Codex execution. Importing this module does nothing."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from sr_grouping import (
    GROUP_NAME, SETUP_GROUP_NAMES, SETUP_COLORS, GroupingSession,
    TradeSetupSession, completion_instructions, target_identity,
)


DEFAULT_SYMBOL = "BYBIT:XAUUSDT.P"
DEFAULT_MODEL = "gpt-6-astra"
TIMEFRAMES = ("1H", "4H", "1D", "15m")
PROJECT_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def prepare_frozen_runtime():
    """Call after Tk loads, before workers launch system-installed programs."""
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        import ctypes
        # PyInstaller's DLL directory must not leak into Node/Codex children.
        # Tk and our Python extensions are already loaded at this point.
        if not ctypes.windll.kernel32.SetDllDirectoryW(None):
            raise ctypes.WinError()


def connector_directory():
    return Path(os.environ.get("SR_TRADINGVIEW_MCP_DIR", Path.home() / "tradingview-mcp")).expanduser().resolve()


def node_executable():
    """Resolve Node even with Explorer's PATH, without changing system settings."""
    override = os.environ.get("SR_NODE_PATH")
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"SR_NODE_PATH does not exist: {path}")
        return str(path)
    found = shutil.which("node.exe") or shutil.which("node")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe",
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Programs" / "nodejs" / "node.exe",
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


# Only these MCP capabilities are authorized for Codex's confirmed analysis stage.
# The app owns a separate, explicitly confirmed symbol-selection operation.
# In particular: no deletion, arbitrary JS/UI input, symbol/tab switching,
# indicator changes, trading, or general-purpose execution tools.
TRADINGVIEW_SR_TOOLS = (
    "chart_get_state", "tab_list", "pane_list", "chart_get_visible_range",
    "data_get_ohlcv", "chart_set_timeframe", "draw_shape", "draw_list",
    "draw_get_properties",
)


def support_resistance_mcp_arguments():
    """Invocation-only policy; callers use this only after explicit consent.

    Keep the CLI's noninteractive approval policy and filesystem sandbox intact.
    Authorize named MCP tools through Codex's supported per-tool settings.
    """
    arguments = ["-c", "mcp_servers.tradingview.enabled_tools=" + json.dumps(TRADINGVIEW_SR_TOOLS)]
    for tool in TRADINGVIEW_SR_TOOLS:
        arguments += ["-c", f'mcp_servers.tradingview.tools.{tool}.approval_mode="approve"']
    return arguments


@dataclass
class AnalysisOutcome:
    status: str
    response: str = ""
    errors: str = ""
    return_code: int | None = None
    output: str = ""
    prompt: str = ""
    # A process exit code is never evidence that chart objects were created.
    drawings_verified: bool = False
    analysis_completed: bool = False
    final_analysis: str = ""
    trade_report: dict | None = None
    telegram_delivery: object | None = None


def sanitize_output(value):
    """Remove terminal escapes and common credential formats from displayed logs."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value or "")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", text)
    text = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[REDACTED]", text)
    text = re.sub(
        r'''(?i)(["']?(?:[\w-]*(?:api[_-]?key|token|secret|password))["']?\s*[:=]\s*)["']?[^\s,"'}]+["']?''',
        r"\1[REDACTED]", text,
    )
    return text


def fallback_symbols():
    """User-configured choices, never presented as a retrieved watchlist."""
    configured = os.environ.get("SR_SYMBOLS", "").split(",")
    return list(dict.fromkeys([DEFAULT_SYMBOL] + [s.strip() for s in configured if s.strip()]))


def get_tradingview_watchlist(timeout=25):
    """Reuse the installed connector's CLI and its watchlist_get implementation."""
    try:
        connector = connector_directory()
        node = node_executable()
        launcher = connector / "src" / "cli" / "index.js"
        if not node or not launcher.is_file():
            raise FileNotFoundError("Existing TradingView connector CLI or Node.js was not found.")
        result = subprocess.run(
            [node, str(launcher), "watchlist", "get"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=connector, timeout=timeout, shell=False,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise ValueError(result.stderr.strip() or f"Connector exited with code {result.returncode}.")
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or data.get("success") is not True:
            raise ValueError("Connector did not return a successful watchlist response.")
        symbols = list(dict.fromkeys(
            row["symbol"].strip() for row in data.get("symbols", [])
            if isinstance(row, dict) and isinstance(row.get("symbol"), str)
            and re.fullmatch(r"[A-Za-z0-9_]+:[A-Za-z0-9_.!/-]+", row["symbol"].strip())
        ))
        if not symbols:
            raise ValueError("TradingView returned an empty watchlist.")
        return {"symbols": symbols, "source": "live", "name": data.get("list_name") or "current list", "error": ""}
    except subprocess.TimeoutExpired:
        error = f"Watchlist retrieval timed out after {timeout} seconds."
    except (OSError, ValueError, TypeError) as exc:
        error = sanitize_output(exc)
    return {"symbols": fallback_symbols(), "source": "fallback", "name": "", "error": error}


def load_codex_models(catalog_path=None):
    """Read visible CLI model IDs locally; listing is not proof of invocation access."""
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    path = Path(catalog_path) if catalog_path is not None else home / "models_cache.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        models = list(dict.fromkeys(
            item["slug"] for item in data.get("models", [])
            if isinstance(item, dict) and item.get("visibility") == "list"
            and item.get("supported_in_api") is not False
            and isinstance(item.get("slug"), str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+", item["slug"])
        ))
        if not models:
            raise ValueError("No visible models were found in the local Codex catalog.")
        return {"models": models, "source": str(path), "fetched_at": data.get("fetched_at", "unknown"), "error": ""}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {"models": [], "source": str(path), "error": sanitize_output(exc)}


def verify_tradingview_chart(symbol, timeout=15):
    """Strict read-only destination verification; never allows a mismatch."""
    return _read_tradingview_chart(symbol, timeout)


def inspect_tradingview_chart(timeout=15):
    """Read the exact current source chart for the GUI's switch confirmation."""
    return _read_tradingview_chart(None, timeout)


def _read_tradingview_chart(expected_symbol, timeout):
    """Read existing tab_list/chart_get_state/pane_list cores; never switch targets.

    Without reliable active-tab attribution, require exactly one chart tab and
    one identified active pane. Ambiguity stops execution rather than guessing.
    """
    connector = connector_directory()
    node = node_executable()
    launcher = connector / "src" / "cli" / "index.js"
    if not node or not launcher.is_file():
        raise ValueError("TradingView chart unavailable: existing connector CLI or Node.js was not found.")

    def read(*args):
        try:
            result = subprocess.run(
                [node, str(launcher), *args], capture_output=True, text=True,
                encoding="utf-8", errors="replace", cwd=connector, timeout=timeout,
                stdin=subprocess.DEVNULL,
                shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode:
                raise ValueError(result.stderr.strip() or f"Connector exited with code {result.returncode}.")
            data = json.loads(result.stdout)
            if not isinstance(data, dict) or data.get("success") is not True:
                raise ValueError("Connector could not read the current chart.")
            return data
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise ValueError("TradingView chart unavailable: " + sanitize_output(exc)) from None

    tabs = read("tab", "list").get("tabs")
    if not isinstance(tabs, list) or len(tabs) != 1 or not isinstance(tabs[0], dict):
        raise ValueError("TradingView chart unavailable or ambiguous. Use one dedicated chart tab and one pane, then try again.")
    tab = tabs[0]
    if tab.get("is_chart") is not True or not tab.get("id") or not tab.get("url"):
        raise ValueError("TradingView chart unavailable: no identifiable chart tab is open.")
    state = read("state")
    symbol = state.get("symbol")
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z0-9_]+:[A-Za-z0-9_.!/-]+", symbol):
        raise ValueError("The current chart must expose its full exchange-qualified symbol.")
    if expected_symbol is not None and symbol != expected_symbol:
        raise ValueError(f"Symbol mismatch: selected {expected_symbol}; TradingView shows {symbol}. Analysis was not started.")
    if type(state.get("chartType")) is not int or state["chartType"] != 1:
        raise ValueError("TradingView must use standard Candles (chart type 1). Change the chart type yourself, then try again.")
    layout = read("pane", "list")
    panes = layout.get("panes")
    if layout.get("chart_count") != 1 or not isinstance(panes, list) or len(panes) != 1:
        raise ValueError("Cannot attribute one exact chart pane. Use a dedicated single-chart layout, then try again.")
    pane = panes[0]
    if (not isinstance(pane, dict) or type(pane.get("index")) is not int
            or layout.get("active_index") != pane["index"] or pane.get("symbol") != symbol):
        raise ValueError("Current TradingView pane identity is unavailable or mismatched. Codex was not started.")
    # Detect tab changes during these reads. Codex must recheck the same identity
    # and candlestick type before analysis and immediately before drawing.
    final_tabs = read("tab", "list").get("tabs")
    if final_tabs != tabs:
        # Titles can include changing quotes; compare stable fields only.
        if (not isinstance(final_tabs, list) or len(final_tabs) != 1
                or not isinstance(final_tabs[0], dict)
                or any(final_tabs[0].get(k) != tab.get(k) for k in ("id", "url", "is_chart", "chart_id"))):
            raise ValueError("TradingView target changed during verification. No analysis was started; confirm again.")
    identity = {
        "tab_id": tab["id"], "url": tab["url"], "chart_id": tab.get("chart_id"),
        "pane_index": pane["index"], "layout": layout.get("layout"),
        "symbol": symbol, "chart_type": 1,
    }
    return json.dumps(target_identity(identity), ensure_ascii=True)


# Application-owned Node program: call the EXISTING connector core/setter and
# wait helpers, not a new chart API implementation or model-supplied page JS.
# A single cached CDP connection is checked against the approved source tab ID.
_SELECT_SYMBOL_PROGRAM = r"""
import * as chart from './src/core/chart.js';
import * as tab from './src/core/tab.js';
import * as pane from './src/core/pane.js';
import {waitForChartRender} from './src/wait.js';
import {getTargetInfo, disconnect} from './src/connection.js';
let input = ''; for await (const chunk of process.stdin) input += chunk;
try {
 const p = JSON.parse(input), t = p.approved_target;
 if (!/^[A-Za-z0-9_]+:[A-Za-z0-9_.!/-]+$/.test(p.destination)) throw Error('Full destination symbol required');
 async function check(symbol) {
   const tabs = await tab.list(), state = await chart.getState(), panes = await pane.list();
   const connected = await getTargetInfo();
   const tabs2 = await tab.list();
   for (const list of [tabs, tabs2]) {
     if (list.tab_count !== 1 || list.tabs.length !== 1 || list.tabs[0].is_chart !== true
         || list.tabs[0].id !== t.tab_id || list.tabs[0].url !== t.url || list.tabs[0].chart_id !== t.chart_id)
       throw Error('Approved chart tab changed; stopped');
   }
   if (connected.id !== t.tab_id || connected.url !== t.url || state.symbol !== symbol || state.chartType !== 1
       || panes.layout !== t.layout || panes.chart_count !== 1 || panes.active_index !== t.pane_index
       || panes.panes.length !== 1 || panes.panes[0].index !== t.pane_index || panes.panes[0].symbol !== symbol)
     throw Error('Approved chart/pane/layout/symbol/candlestick identity mismatch');
 }
 await check(t.symbol);
 // The only mutation is this existing MCP-backed operation, once if needed.
 const changed = t.symbol === p.destination
   ? {success:true,symbol:p.destination,chart_ready:null}
   : await chart.setSymbol({symbol:p.destination});
 if (changed.success !== true || changed.symbol !== p.destination) throw Error('Connector rejected the requested symbol');
 // setSymbol's legacy header-text wait may return false even with a loaded exact
 // symbol. Use the existing canvas/spinner/stable-symbol render wait as well.
 const ready = await waitForChartRender();
 if (ready !== true) throw Error('Chart loading/render readiness timed out');
 await check(p.destination);
 console.log(JSON.stringify({success:true, symbol:p.destination, chart_ready:ready,
   connector_symbol_ready:changed.chart_ready}));
} catch (e) {
 console.log(JSON.stringify({success:false, error:e.message})); process.exitCode=1;
} finally { await disconnect(); }
"""


def ensure_selected_symbol(symbol, approved_chart, *, live_confirmed=False, timeout=35):
    """One explicitly approved symbol selection on the same dedicated chart.

    Existing strict verification stays unchanged for all analysis/drawing calls.
    No retries/recovery, aliases, tab/pane selection or model permissions added.
    """
    if not live_confirmed:
        raise ValueError("Explicit confirmation of this symbol selection is required.")
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z0-9_]+:[A-Za-z0-9_.!/-]+", symbol):
        raise ValueError("Select a full exchange-qualified symbol; bare aliases are not accepted.")
    approved = target_identity(approved_chart)
    # Share the existing job lock: never switch while another app instance is
    # analyzing. The subsequent analysis takes this lock again and re-verifies.
    session = GroupingSession(approved, verify_tradingview_chart, connector_directory(), node_executable())
    with session.exclusive():
        if target_identity(inspect_tradingview_chart()) != approved:
            raise ValueError("TradingView changed since confirmation. Nothing was switched; confirm again.")
        connector, node = connector_directory(), node_executable()
        if not node or not (connector / "src" / "core" / "chart.js").is_file():
            raise ValueError("Existing TradingView connector or Node.js unavailable; no switch attempted.")
        try:
            result = subprocess.run(
                [node, "--input-type=module", "-e", _SELECT_SYMBOL_PROGRAM],
                input=json.dumps({"approved_target": approved, "destination": symbol}, ensure_ascii=True),
                capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=connector,
                timeout=timeout, shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                data = json.loads(result.stdout)
            except ValueError:
                raise ValueError(result.stderr.strip() or "Existing connector returned no valid symbol-selection response.") from None
            if result.returncode or not isinstance(data, dict) or data.get("success") is not True:
                raise ValueError(data.get("error", "Existing connector symbol selection failed.") if isinstance(data, dict) else "Invalid connector response.")
            if data.get("symbol") != symbol or data.get("chart_ready") is not True:
                raise ValueError("Exact destination symbol and chart readiness were not confirmed.")
            verified = target_identity(verify_tradingview_chart(symbol))
            if verified != dict(approved, symbol=symbol):
                raise ValueError("An unexpected tab/chart/layout/pane changed during symbol selection.")
            return json.dumps(verified, ensure_ascii=True)
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
            raise ValueError("Symbol selection stopped: " + sanitize_output(exc)
                             + " The symbol may have changed. Inspect TradingView; no automatic retry or recovery. Codex was not started.") from None


def build_all_charts_prompt(timeframes, levels_per_side=3, model=DEFAULT_MODEL):
    # Reuse existing input validation. No watchlist or analysis is executed here.
    build_support_resistance_prompt(DEFAULT_SYMBOL, timeframes, levels_per_side, model)
    return (
        "CONCEPT ONLY — ALL CHARTS IS NOT IMPLEMENTED BY THIS APPLICATION.\n\n"
        f"Requested model: {model}\nTimeframes: {', '.join(dict.fromkeys(timeframes))}\n"
        f"Future request: find {levels_per_side} support and {levels_per_side} resistance zones "
        "per chart in the currently selected TradingView watchlist, combining timeframe confluence.\n"
        "This is a conceptual request only, with no authorization to iterate charts, run analysis "
        "or change TradingView. A future implementation would need explicit approval and exact "
        "chart identity checks for every target. Do not execute this request.\n"
    )


def build_support_resistance_prompt(
    symbol, timeframes, levels_per_side=3, model=DEFAULT_MODEL, *,
    confirmed_chart="", live_confirmed=False,
):
    symbol = str(symbol).strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+:[A-Za-z0-9_.!/-]+", symbol):
        raise ValueError("Enter an exchange-qualified TradingView symbol, e.g. BYBIT:XAUUSDT.P.")
    frames = list(dict.fromkeys(timeframes))
    if not frames or any(frame not in TIMEFRAMES for frame in frames):
        raise ValueError("Select at least one of 1H, 4H, 1D or 15m.")
    if isinstance(levels_per_side, bool) or not isinstance(levels_per_side, int) or not 1 <= levels_per_side <= 20:
        raise ValueError("Levels per side must be a whole number from 1 to 20.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(model)):
        raise ValueError("Enter a valid Codex model ID.")
    chart = str(confirmed_chart).strip()
    if live_confirmed and not chart:
        raise ValueError("An exact tab/layout/pane identity is required before live execution.")
    approval = (
        f"The user explicitly approved this single request. Automatically verified chart identity: {chart!r}.\n"
        "Read the actual chart identity and compare it with this approved target before any mutation. "
        "If the identity is unavailable, ambiguous, or mismatched, STOP without changes and explain.\n"
        if live_confirmed else
        "There is NO authorization for live chart changes yet. First use read-only MCP tools to report "
        "the exact tab, layout, active pane, exchange-qualified symbol and timeframe. Ask the user "
        "to explicitly confirm that exact identity and this drawing request. STOP and wait for "
        "their reply before changing timeframes, symbols, or drawings.\n"
    )
    return (
        "Trade With AM — Support & Resistance Agent\n\n"
        f"Requested model: {model}. This is a fresh request; do not assume shared chat/session state.\n"
        f"TradingView symbol: {symbol}\n"
        f"Analyze timeframes: {', '.join(frames)}\n"
        f"Find {levels_per_side} nearby support levels/areas and {levels_per_side} nearby resistance levels/areas "
        "TOTAL across the selected timeframes, combining confluence rather than multiplying the count per timeframe.\n\n"
        "Use only the existing configured TradingView MCP connector. The installed connector is at "
        f"{connector_directory()} and uses TradingView Desktop debugging port 9222. "
        "Do not install, rebuild or replace it. Do not run the debug launcher, close TradingView, "
        "use another data provider, or connect to the Bybit API. If MCP is unavailable, stop and report it.\n\n"
        + approval + "\n"
        "Before analysis or drawing, read the chart state and available tab/pane identity using read-only MCP tools. "
        f"Verify that the exact active target is {symbol}, including exchange and perpetual/contract suffix. "
        "Require standard Candles (chartType 1) and the same verified tab/pane identity; stop if unavailable or mismatched. "
        "Never switch to another symbol, tab, layout or pane to make it match. If more than one possible "
        "target exists and cannot be distinguished, stop. Recheck the same identity immediately before drawing.\n\n"
        "After explicit authorization, analyze visible price structure and available chart data on the selected "
        "timeframes. You may change timeframe only on the confirmed target, and restore its original timeframe "
        "when finished. Identify nearby meaningful levels or zones around current price; explain timeframe confluence "
        "and reasons briefly. Use actual data, never invent prices or force unsupported levels.\n"
        "Choose the drawing type for each level from market structure, repeated price reactions, swing levels "
        "and timeframe confluence. Use horizontal_line for a relatively precise support/resistance price. "
        "Use rectangle only for a genuine zone with meaningful lower and upper price boundaries. "
        "Do not force all levels to be zones or all levels to be lines, and do not force a mixture without evidence. "
        "Each line or zone counts as one level/area toward the requested total per side. "
        "Use red (#ff0000) for resistance and green (#008000) for support, applying connector-supported "
        "style overrides appropriate to each shape; match rectangle borders and fills where supported.\n"
        "Visible chart labels must contain ONLY prices and contributing timeframes. "
        "For a rectangle use 'LOW–HIGH | TF / TF'; for a horizontal line use 'PRICE | TF / TF'. "
        "Format examples only, not market levels: zone '4155.35–4161.06 | 1H / 4H / 1D'; "
        "line '4174.50 | 1H / 4H'. Use actual prices with instrument-appropriate precision and "
        "only selected timeframes that contribute to that level. Do not prefix visible labels with "
        "'Trade With AM', 'S1 Support', 'S2 Support', 'R1 Resistance', 'R2 Resistance', or any role/sequence label. "
        "Color distinguishes support from resistance. If label/style rendering is unsupported, report it "
        "without retrying or changing existing drawings.\n"
        "Preserve ownership information in documented separate internal identification or hidden metadata "
        "for newly created objects ONLY if the connector supports it. Do not invent metadata fields or tools. "
        "If hidden ownership metadata is unsupported, clearly report that limitation. Record returned new "
        "drawing IDs in the response with the verified target, support/resistance role, geometry and timeframes; "
        "these identify this run's new objects and are not proof of ownership of existing objects. "
        "Never infer ownership from color or simplified price/timeframe labels, and never automatically "
        "modify or delete ambiguously owned objects. The standalone application groups verified new drawings "
        "under 'Support and Resistance Levels' after analysis. Do not attempt grouping yourself or invent "
        "a tool or workaround that edits existing objects.\n"
        "Preserve all existing drawings and indicators. Never delete, replace, move or regroup existing objects. "
        "Do not place orders, change alerts, open trading panels, or process other charts/watchlist entries. "
        "Do not implement algorithms, agents, schedulers or write project files.\n"
        "Do not automatically retry a failed drawing call. On failure, stop and list any objects already created "
        "and any partial changes; do not clean them up. Read back the new drawing IDs/properties if supported. "
        "Report the verified target identity, chosen line/zone types and prices/bounds, evidence of created object IDs, grouping "
        "support, and any errors. Distinguish planned, attempted, confirmed and unverified drawings. "
        "A zero subprocess exit code is not proof of drawing success.\n"
    )


def codex_command():
    """Resolve the installed CLI without shell=True or executing an npm .cmd shim."""
    override = os.environ.get("SR_CODEX_PATH")
    found = override or shutil.which("codex.exe") or shutil.which("codex")
    if not found and os.name == "nt":
        # Explorer may not have picked up npm's user PATH entry yet.
        npm_shim = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "npm" / "codex.cmd"
        if npm_shim.is_file():
            found = str(npm_shim)
    if not found:
        raise FileNotFoundError("Codex CLI was not found. Add it to PATH or set SR_CODEX_PATH.")
    path = Path(found).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Codex CLI path does not exist: {path}")
    if path.suffix.lower() in (".cmd", ".bat", ".ps1"):
        path = path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        if not path.is_file():
            raise FileNotFoundError("Cannot resolve the npm Codex launcher. Set SR_CODEX_PATH to codex.exe.")
    if path.suffix.lower() in (".js", ".mjs"):
        if os.name == "nt":
            # Use the native binary so timeout terminates Codex itself, not just
            # its Node launcher while leaving an analysis child running.
            package = path.parent.parent
            binaries = list(package.glob("node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe"))
            binaries += list(package.glob("vendor/*/bin/codex.exe"))
            if len(binaries) != 1:
                raise FileNotFoundError("Set SR_CODEX_PATH to the installed native codex.exe (could not resolve one unique binary).")
            return [str(binaries[0])]
        node = node_executable()
        if not node:
            raise FileNotFoundError("Node.js is required by this installed Codex launcher.")
        return [node, str(path)]
    return [str(path)]


def run_support_resistance_analysis(
    symbol, timeframes, levels_per_side=3, model=DEFAULT_MODEL, *,
    confirmed_chart="", live_confirmed=False, timeout=600,
):
    """Run once after caller obtains consent. No Tk dependency, retries or GUI side effects.

    Without live_confirmed=True and a chart identity, returns confirmation_required
    before launching any subprocess. The caller is responsible for obtaining consent.
    """
    try:
        prompt = build_support_resistance_prompt(
            symbol, timeframes, levels_per_side, model,
            confirmed_chart=confirmed_chart, live_confirmed=live_confirmed,
        )
    except (ValueError, TypeError) as exc:
        return AnalysisOutcome("invalid_input", errors=str(exc))
    if not live_confirmed:
        return AnalysisOutcome("confirmation_required", prompt=prompt,
                               errors="Explicit live-test approval and exact chart identity are required.")
    try:
        session = GroupingSession(confirmed_chart, verify_tradingview_chart, connector_directory(), node_executable())
        if session.target["symbol"] != symbol:
            raise ValueError("Approved chart symbol differs from the selected symbol.")
        with session.exclusive():
            try:
                session.prepare()
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                return AnalysisOutcome("grouping_preflight_failed", prompt=prompt, errors=sanitize_output(exc))
            prompt += completion_instructions(session)
            outcome = _execute_codex(prompt, model, timeout)
            if outcome.status == "completed_unverified":
                try:
                    path = session.finish(outcome.response, levels_per_side)
                    outcome.status = "completed_verified"
                    outcome.drawings_verified = True
                    outcome.output += f"\nApplication verified drawing properties and exact group membership. Ownership record: {path}"
                except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
                    outcome.status = "partial_success" if session.record["drawing_ids"] else "completed_unverified"
                    outcome.errors += "\nDrawing/group verification incomplete: " + sanitize_output(exc)
            if not outcome.drawings_verified:
                try:
                    session.save(outcome.status, error=outcome.errors)
                except OSError as exc:
                    outcome.errors += "\nCould not save ownership record: " + sanitize_output(exc)
                outcome.errors += "\nPartial chart changes may exist. Preserved without cleanup or automatic retry; inspect TradingView before another request."
            return outcome
    except (OSError, ValueError, TypeError) as exc:
        return AnalysisOutcome("grouping_preflight_failed", prompt=prompt, errors=sanitize_output(exc))


def build_trade_setup_prompt(
    symbol, timeframes=("1H", "4H", "1D"), model=DEFAULT_MODEL, *,
    confirmed_chart="", live_confirmed=False,
):
    """Separate price-action request; no S/R count or algorithm is reused."""
    frames = list(dict.fromkeys(timeframes))
    build_support_resistance_prompt(symbol, frames, 1, model,
                                    confirmed_chart=confirmed_chart, live_confirmed=live_confirmed)
    consent = (
        f"Explicit approval covers this single conditional setup analysis and its verified new drawings/groups. Approved identity: {confirmed_chart}. "
        if live_confirmed else
        "NO live chart changes are authorized. Read and report exact chart identity, then STOP for explicit user confirmation. "
    )
    return (
        "Trade With AM — Conditional Price Action Trade Setups\n"
        f"Requested Codex model: {model}\nSelected symbol: {symbol}\nAnalysis timeframes: {', '.join(frames)}\n"
        + consent + "\n"
        "Use only the existing configured TradingView MCP. Do not install or modify connectors/configuration. "
        "Before analysis, timeframe changes and each drawing, verify the exact exchange-qualified selected symbol, "
        "tab ID, URL/chart ID, layout and active pane against the approved identity, requiring standard Candles (chartType 1). "
        "Stop on ambiguity/mismatch. Never switch symbol, tab, layout or pane. Change only selected analysis timeframes "
        "on that target, restoring its original timeframe when finished. No other charts or watchlist iteration.\n"
        f"Inspect existing drawings and the Object Tree group '{GROUP_NAME}'. The application supplies a verified "
        "group/membership snapshot below; compare relevant IDs and properties using draw_list/draw_get_properties. "
        "Consider existing S/R only if still relevant to current evidence. Explain which outdated levels need refreshing "
        "and why; never overwrite or silently refresh them. Do not infer ownership from labels/colors. "
        "If S/R is absent, identify relevant levels from current chart evidence. Only when the supplied snapshot "
        "has no S/R group and no conflicting ownership, you may create up to three evidence-backed supports and three "
        "resistances as new lines/rectangles, recording them in sr_drawings. The application verifies/groups them. "
        "If safety or evidence is insufficient, create no S/R drawings and explain what is missing. "
        "Do not adopt, move, delete, replace, regroup or modify ANY existing drawing, indicator or group.\n"
        "Analyze market trend and structure, higher highs / higher lows, lower highs / lower lows, breakout and retest, "
        "trend continuation, pullbacks to support/resistance, technically justified failed breakouts, and relevant "
        "candlestick confirmation. Use actual current chart data and selected timeframe confluence; never invent prices. "
        "Identify up to THREE worthwhile CONDITIONAL setups, ranked by relative technical strength/confluence: "
        "Setup 1 — Primary; Setup 2 — Secondary; Setup 3 — Alternative. Do not fabricate numerical success probabilities "
        "or claim a trade will succeed. Return fewer than three when warranted; if none are attractive, return "
        "NO TRADE / WAIT with concrete reasons and no placeholder setups/drawings/groups.\n"
        "For every valid setup explain LONG or SHORT, strategy type, market structure reasoning, entry area, required "
        "price-action confirmation, invalidation / protective stop concept, Target 1, Target 2 only when justified, "
        "approximate risk/reward only when supportable (explain assumptions; otherwise unavailable), and conditions "
        "that cancel the idea. Confirmation must occur before considering an entry; all ideas remain conditional.\n"
        "For each valid setup draw real entry areas/levels, confirmation triggers, invalidation levels and target levels "
        "using the verified horizontal_line and rectangle shapes with short explanatory labels. Represent direction "
        "in labels; do not probe unsupported directional arrows. Each setup needs four to eight drawings including "
        "roles entry, confirmation, invalidation, target1; target2 is optional. Use consistent distinct scenario colors: "
        f"Setup 1 {SETUP_COLORS[0]}, Setup 2 {SETUP_COLORS[1]}, Setup 3 {SETUP_COLORS[2]}. "
        "Match rectangle borders/fills where supported. Any optional new S/R uses green #008000 for support and red "
        "#ff0000 for resistance, with price/timeframe-only labels. Record returned new IDs and actual point/property "
        "readbacks; never claim an unverified object succeeded. No automatic retry or cleanup after a partial failure.\n"
        f"The application alone creates independent Object Tree groups: {', '.join(SETUP_GROUP_NAMES)}. "
        "Do not group drawings yourself or request ui_evaluate/arbitrary JavaScript, UI automation or shell workarounds. "
        "An existing setup group requires ownership inspection and operator review; do not overwrite or duplicate it.\n"
        "No Bybit/exchange/trading API integration, order placement, live account actions, automatic trade execution, "
        "Telegram, alerts, trading panels, account access, general-purpose execution or project file changes. "
        "This request is conditional chart analysis and annotations only.\n"
    )


def _trade_completion_instructions(session):
    sr_groups = [g for g in session.before["groups"] if g["name"] == GROUP_NAME]
    member_ids = {eid for g in sr_groups for eid in g["ids"]}
    context = {"groups": sr_groups, "drawings": [d for d in session.before["drawings"] if d["id"] in member_ids]}
    return (
        "\nAPPLICATION-VERIFIED S/R GROUP CONTEXT (read-only; not permission to adopt objects):\n"
        + json.dumps(context, ensure_ascii=True) + "\nFINAL-MESSAGE PROTOCOL\n"
        "Return ONLY a JSON object, without Markdown fences. Required fields: schema=1, "
        f"run_id={json.dumps(session.run_id)}, target={json.dumps(session.target)}, "
        "status='complete' only for a completed analysis with all requested readbacks and restored timeframe, "
        "otherwise 'incomplete'; errors (array), decision ('setups' or 'wait'), final_analysis (string), "
        "setups (array of zero to three), sr_drawings (array, empty unless safe new S/R was drawn). "
        "final_analysis must contain ONLY your complete final human-readable conditional setup explanations, "
        "including rankings, all requested fields and S/R refresh/missing-level observations, or NO TRADE / WAIT "
        "with reasons. Exclude prompts, raw JSON, MCP calls, execution traces, diagnostics and success claims "
        "about grouping, which the application has not yet performed.\n"
        "Each setup object requires rank (consecutive integer from 1), direction ('LONG'/'SHORT'), strategy_type, "
        "reasoning, entry_area, confirmation, invalidation, target1, cancel_conditions (nonempty strings), "
        "target2 and risk_reward (explanatory strings when supported, otherwise null), drawings (array). "
        "Each drawing requires id (actual returned new ID), role, shape ('horizontal_line'/'rectangle'), "
        "points (actual readback [{time,price}]), properties (actual readback subset including text and linecolor "
        "for lines, text/color/backgroundColor for rectangles). Setup roles: entry, confirmation, invalidation, "
        "target1, optional target2. sr_drawings roles: support/resistance. Do not omit or reuse drawing IDs.\n"
    )


def run_trade_setup_analysis(
    symbol, timeframes=("1H", "4H", "1D"), model=DEFAULT_MODEL, *,
    confirmed_chart="", live_confirmed=False, timeout=600,
):
    """One confirmed price-action job using the existing CLI/lock/connector."""
    try:
        prompt = build_trade_setup_prompt(symbol, timeframes, model,
                                         confirmed_chart=confirmed_chart, live_confirmed=live_confirmed)
    except (ValueError, TypeError) as exc:
        return AnalysisOutcome("invalid_input", errors=str(exc))
    if not live_confirmed:
        return AnalysisOutcome("confirmation_required", prompt=prompt, errors="Explicit confirmation and exact chart identity are required.")
    try:
        session = TradeSetupSession(confirmed_chart, verify_tradingview_chart, connector_directory(), node_executable())
        if session.target["symbol"] != symbol:
            raise ValueError("Approved chart symbol differs from the selected symbol.")
        with session.exclusive():
            try:
                session.prepare()
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                return AnalysisOutcome("grouping_preflight_failed", prompt=prompt, errors=sanitize_output(exc))
            prompt += _trade_completion_instructions(session)
            outcome = _execute_codex(prompt, model, timeout)
            if outcome.status == "completed_unverified":
                try:
                    count = session.finish(outcome.response)
                    outcome.status = "completed_verified" if count else "completed_no_trade"
                    outcome.drawings_verified = True
                    outcome.output += f"\nApplication verified {count} setup groups and chart preservation. Ownership record: {session.path}"
                except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
                    outcome.status = "partial_success" if session.record["drawing_ids"] else "completed_unverified"
                    outcome.errors += "\nTrade setup drawing/group verification incomplete: " + sanitize_output(exc)
                outcome.analysis_completed = getattr(session, "analysis_completed", False)
                outcome.final_analysis = sanitize_output(getattr(session, "final_analysis", ""))
                outcome.trade_report = getattr(session, "completed_report", None)
            if not outcome.drawings_verified:
                outcome.errors += "\nPartial changes may exist. No automatic retry or cleanup; inspect TradingView before another request."
                try:
                    session.save(outcome.status, error=outcome.errors)
                except OSError as exc:
                    outcome.errors += "\nCould not save ownership record: " + sanitize_output(exc)
            return outcome
    except (OSError, ValueError, TypeError) as exc:
        return AnalysisOutcome("grouping_preflight_failed", prompt=prompt, errors=sanitize_output(exc))


def _execute_codex(prompt, model, timeout):
    """One CLI invocation; grouping and verification stay in the application."""
    try:
        command = codex_command()
        environment = os.environ.copy()
        node = node_executable()
        if node:
            # The existing MCP config launches "node" by name. Explorer may
            # have a stale PATH, so give this child the discovered Node folder.
            environment["PATH"] = str(Path(node).parent) + os.pathsep + environment.get("PATH", "")
        # A separate CLI process loads the user's existing CODEX_HOME/config.toml.
        # Reuse the connector transport/auth. Override only this invocation's
        # exposed TradingView tools and their approval modes, after consent.
        with tempfile.TemporaryDirectory(prefix="trade_with_am_") as folder:
            final_file = Path(folder) / "response.txt"
            command += ["exec"] + support_resistance_mcp_arguments() + [
                "--model", model, "--sandbox", "read-only",
                "--skip-git-repo-check", "--color", "never",
                "--output-last-message", str(final_file), "-",
            ]
            completed = subprocess.run(
                command, input=prompt, capture_output=True, text=True,
                encoding="utf-8", errors="replace", cwd=PROJECT_DIR,
                env=environment,
                timeout=timeout, shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # The final message is separate from stdout/tool logs. No log fallback.
            response = sanitize_output(final_file.read_text(encoding="utf-8", errors="replace")) if final_file.exists() else ""
            output = sanitize_output(completed.stdout)
            errors = sanitize_output(completed.stderr)
            status = "completed_unverified" if completed.returncode == 0 else "failed"
            transcript = "\n".join((response, output, errors)).lower()
            if "mcp tool call requires approval" in transcript and "approval policy is never" in transcript:
                status = "approval_blocked"
                errors += (
                    "\nCodex reported an MCP tool approval block. No automatic retry was attempted. "
                    "Use Copy Prompt in your interactive Codex/Astra session and approve only the required "
                    "TradingView tools, retaining the exact chart checks. Inspect the chart for partial "
                    "changes before another request. A managed policy may still require interactive approval."
                )
            return AnalysisOutcome(
                status,
                response=response,
                errors=errors,
                return_code=completed.returncode,
                output=output,
                prompt=prompt,
            )
    except subprocess.TimeoutExpired as exc:
        return AnalysisOutcome(
            "timed_out", errors=f"Codex exceeded {timeout} seconds. Partial chart changes may exist. "
            "Inspect TradingView before another request. No automatic retry.\n" + sanitize_output(exc.stderr),
            output=sanitize_output(exc.stdout), prompt=prompt,
        )
    except OSError as exc:
        return AnalysisOutcome("launch_error", errors=sanitize_output(exc), prompt=prompt)
