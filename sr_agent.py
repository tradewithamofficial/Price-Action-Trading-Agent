"""Reusable S/R requests and Codex execution. Importing this module does nothing."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from sr_grouping import ChartSession, target_identity, verify_readbacks


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


# Codex inherits the existing MCP configuration; no new tool grants are injected.
# Its filesystem sandbox is separate from MCP approval and tool availability.
# The app owns an explicitly confirmed symbol-selection operation before analysis.
# Tool denials stop execution; the prompt cannot override a permission boundary.




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
    response_file: str = ""
    verification_details: str = ""
    run_id: str = ""


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
    session = ChartSession(approved, verify_tradingview_chart, connector_directory(), node_executable())
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

def validate_selection(symbol, timeframes, levels_per_side=3, model=DEFAULT_MODEL):
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z0-9_]+:[A-Za-z0-9_.!/-]+", symbol):
        raise ValueError("Enter a full exchange-qualified TradingView symbol, e.g. BYBIT:BTCUSDT.P.")
    if not isinstance(timeframes, (list, tuple)) or set(timeframes) != {"1H", "4H", "1D"} or len(timeframes) != 3:
        raise ValueError("The tested prompts require 1H, 4H and 1D together. Select all three and leave 15m unchecked.")
    if type(levels_per_side) is not int or not 1 <= levels_per_side <= 20:
        raise ValueError("Levels per side must be a whole number from 1 to 20.")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", model):
        raise ValueError("Select a valid model from your installed Codex catalog.")


def prompt_directory():
    bundled = Path(__file__).resolve().parent / "reference_simple"
    external = PROJECT_DIR / "reference_simple"
    return external if getattr(sys, "frozen", False) and external.is_dir() else bundled


def _load_prompt(filename):
    path = prompt_directory() / filename
    try:
        text = path.read_text(encoding="utf-8-sig").strip()
    except OSError as exc:
        raise ValueError(f"Cannot read editable prompt {path}: {exc}") from None
    if not text:
        raise ValueError(f"Prompt file is empty: {path}")
    return text


def _execution_context(symbol, confirmed_chart, live_confirmed):
    if not live_confirmed:
        return "\n\nGUI CONTEXT: No chart changes are authorized. Stop for explicit GUI confirmation.\n"
    target = target_identity(confirmed_chart)
    if target["symbol"] != symbol:
        raise ValueError("Selected symbol differs from the approved chart.")
    return (
        "\n\nGUI-APPROVED TARGET AND SAFETY CONTEXT\n"
        + json.dumps(target, ensure_ascii=False) + "\n"
        "Use the existing configured TradingView MCP on this exact exchange-qualified symbol, tab, saved chart, "
        "layout and single standard-candlestick pane. Verify the target before drawing and stop on mismatch. "
        "Never switch symbol, exchange, tab, layout or pane. Restore the original timeframe. "
        "The analytical instructions above are the editable tested prompt; return the complete human-readable "
        "analysis, not a JSON completion contract. Codex creates the drawings and groups itself. "
        "Preserve every pre-existing drawing, group (including its membership), study and annotation. "
        "If a requested name is occupied, follow the prompt's safe alternative/limitation path; never alter "
        "the occupied group. No automatic retry, cleanup, deletion or replacement. "
        "Do not bypass a tool denial or approval requirement. No trades/orders, account operations, Telegram, "
        "alerts, installation, global configuration changes or reading local credentials/project files.\n"
    )


def build_all_charts_prompt(timeframes, levels_per_side=3, model=DEFAULT_MODEL):
    return "All Charts is not implemented. This application cannot execute a multi-chart request."


def build_support_resistance_prompt(symbol, timeframes, levels_per_side=3, model=DEFAULT_MODEL, *,
                                    confirmed_chart="", live_confirmed=False):
    validate_selection(symbol, timeframes, levels_per_side, model)
    text = _load_prompt("support_resistance.txt")
    if levels_per_side != 3:
        n = levels_per_side
        replacements = {
            "exactly 3 significant resistance": f"exactly {n} significant resistance",
            "exactly 3 significant support": f"exactly {n} significant support",
            "Draw all 6 directly": f"Draw all {2*n} directly",
            "the three nearest prices": f"the {n} nearest prices",
            "among the six.": f"among the {2*n}.",
            "Draw the 3 resistance levels/zones and label them R1, R2, R3":
                f"Draw the {n} resistance levels/zones and label them " + ", ".join(f"R{i}" for i in range(1,n+1)),
            "Draw the 3 support levels/zones and label them S1, S2, S3":
                f"Draw the {n} support levels/zones and label them " + ", ".join(f"S{i}" for i in range(1,n+1)),
            "List R1, R2, R3 and S1, S2, S3":
                "List " + ", ".join(f"R{i}" for i in range(1,n+1)) + " and " + ", ".join(f"S{i}" for i in range(1,n+1)),
        }
        if any(text.count(old) != 1 for old in replacements):
            raise ValueError("This edited S/R prompt cannot safely apply a non-default level count. Use 3 or restore its count markers.")
        for old, new in replacements.items():
            text = text.replace(old,new,1)
    return text + _execution_context(symbol, confirmed_chart, live_confirmed)


def build_trade_setup_prompt(symbol, timeframes=("1H", "4H", "1D"), model=DEFAULT_MODEL, *,
                             confirmed_chart="", live_confirmed=False):
    validate_selection(symbol,timeframes,3,model)
    return _load_prompt("price_action.txt") + _execution_context(symbol,confirmed_chart,live_confirmed)


def codex_failure(response, output, errors):
    """Execution/tool-access failures are not successful market WAIT reports."""
    if re.search(r"(?m)^(?:\d{4}-\S+\s+)?(?:ERROR\b|Error:)", errors):
        return "Codex reported an infrastructure error; the analysis is incomplete."
    if re.search(r"unsupported call:|tool discovery failed|(?:MCP|TradingView) (?:connection|tool call) failed",response,re.I):
        return "TradingView/MCP access failed; this is not a valid market WAIT assessment."
    if re.match(r"\s*(?:FAILURE\b|I (?:cannot|can't|could not|couldn't) (?:access|connect to) (?:the )?(?:TradingView|MCP))",response,re.I):
        return "Codex could not complete the requested analysis."
    return ""


def _execute_codex(prompt, model, timeout):
    """The reference's one CLI/stdin/final-text-file call, with a bounded timeout."""
    response_file = None
    run_id = uuid.uuid4().hex
    try:
        if type(timeout) not in (int,float) or not 0 < timeout <= 3600:
            raise ValueError("Codex timeout must be between zero and 3600 seconds.")
        command = codex_command()
        folder = PROJECT_DIR / "responses" / run_id
        folder.mkdir(parents=True)
        response_file = folder / "final-response.txt"
        environment = os.environ.copy()
        node = node_executable()
        if node:
            environment["PATH"] = str(Path(node).parent) + os.pathsep + environment.get("PATH", "")
        completed = subprocess.run(
            command + ["exec", "--model", model, "--sandbox", "read-only", "--skip-git-repo-check",
                       "--output-last-message", str(response_file), "-"],
            input=prompt, text=True, capture_output=True, encoding="utf-8", errors="replace",
            cwd=prompt_directory(), env=environment, timeout=timeout, shell=False,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
        )
        response = response_file.read_text(encoding="utf-8-sig",errors="replace") if response_file.is_file() else ""
        output, errors = sanitize_output(completed.stdout), sanitize_output(completed.stderr)
        blocked = bool(re.search(r"MCP tool call requires approval|approval review rejected", "\n".join((response,output,errors)), re.I))
        failure = codex_failure(response,output,errors)
        complete = completed.returncode == 0 and bool(response.strip()) and not blocked and not failure
        status = "completed_response" if complete else "approval_blocked" if blocked else "failed"
        if blocked:
            errors += "\nMCP approval was unavailable. No approval policy was bypassed and no operation was retried."
        elif failure:
            errors += "\n" + failure
        elif completed.returncode == 0 and not response.strip():
            errors += "\nCodex produced no final response file/content. Tool logs are not a final analysis."
        (folder/"diagnostics.txt").write_text(output+"\n"+errors,encoding="utf-8")
        return AnalysisOutcome(status,response=response,final_analysis=response,analysis_completed=complete,
            return_code=completed.returncode,output=output,errors=errors,prompt=prompt,
            response_file=str(response_file),run_id=run_id)
    except subprocess.TimeoutExpired as exc:
        response = response_file.read_text(encoding="utf-8-sig",errors="replace") if response_file and response_file.is_file() else ""
        return AnalysisOutcome("timed_out",response=response,final_analysis=response,prompt=prompt,
            errors=f"Codex exceeded {timeout} seconds. Partial chart changes may exist; no automatic retry.\n"+sanitize_output(exc.stderr),
            output=sanitize_output(exc.stdout),response_file=str(response_file or ""),run_id=run_id)
    except (OSError,ValueError) as exc:
        return AnalysisOutcome("launch_error",errors=sanitize_output(exc),prompt=prompt,
                               response_file=str(response_file or ""),run_id=run_id)


def _run_analysis(symbol, timeframes, levels, model, *, trade, confirmed_chart, live_confirmed, timeout):
    try:
        builder = build_trade_setup_prompt if trade else build_support_resistance_prompt
        args = (symbol,timeframes,model) if trade else (symbol,timeframes,levels,model)
        prompt = builder(*args,confirmed_chart=confirmed_chart,live_confirmed=live_confirmed)
        if not live_confirmed:
            return AnalysisOutcome("confirmation_required",prompt=prompt,errors="Explicit GUI confirmation is required.")
        target = target_identity(confirmed_chart)
        session = ChartSession(target,verify_tradingview_chart,connector_directory(),node_executable())
        with session.exclusive():
            before = None
            verification = "Independent drawing/group readback is unavailable."
            try:
                before = session.snapshot()
            except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired) as exc:
                verification += " " + sanitize_output(exc)
            # This check is mandatory even when optional drawing readback is unavailable.
            if target_identity(verify_tradingview_chart(symbol)) != target:
                return AnalysisOutcome("target_mismatch",prompt=prompt,errors="Approved chart changed before Codex. Nothing was launched.")
            outcome = _execute_codex(prompt,model,timeout)
            try:
                if target_identity(verify_tradingview_chart(symbol)) != target:
                    raise ValueError("Approved chart identity changed after execution.")
            except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired) as exc:
                outcome.status = "target_mismatch"
                outcome.analysis_completed = False
                outcome.errors += "\n" + sanitize_output(exc) + " No retry or recovery was attempted."
                return outcome
            try:
                if before is not None:
                    after = session.snapshot()
                    if outcome.response_file:
                        Path(outcome.response_file).with_name("chart-readbacks.json").write_text(
                            json.dumps({"before":before,"after":after},indent=2),encoding="utf-8")
                    verification = verify_readbacks(before,after,trade=trade,levels=levels,response=outcome.response)
                    outcome.drawings_verified = outcome.analysis_completed
            except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired) as exc:
                verification = "Chart/drawing verification incomplete: " + sanitize_output(exc)
            outcome.verification_details = verification
            try:
                if target_identity(verify_tradingview_chart(symbol)) != target:
                    raise ValueError("Approved chart changed during final readback.")
            except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired) as exc:
                outcome.status = "target_mismatch"
                outcome.analysis_completed = outcome.drawings_verified = False
                outcome.errors += "\n" + sanitize_output(exc)
                return outcome
            if not outcome.drawings_verified:
                outcome.errors += "\n"+verification+"\nInspect the chart before another request; no automatic retry or cleanup."
            if trade and outcome.analysis_completed:
                outcome.trade_report = {"format":"plain_text","run_id":outcome.run_id,
                    "cli_completed":True,"final_analysis":outcome.final_analysis}
            return outcome
    except (OSError,ValueError,TypeError,KeyError) as exc:
        return AnalysisOutcome("invalid_input",errors=sanitize_output(exc))


def run_support_resistance_analysis(symbol, timeframes, levels_per_side=3, model=DEFAULT_MODEL, *,
                                    confirmed_chart="", live_confirmed=False, timeout=600):
    return _run_analysis(symbol,timeframes,levels_per_side,model,trade=False,
                         confirmed_chart=confirmed_chart,live_confirmed=live_confirmed,timeout=timeout)


def run_trade_setup_analysis(symbol, timeframes, model=DEFAULT_MODEL, *,
                            confirmed_chart="", live_confirmed=False, timeout=600):
    return _run_analysis(symbol,timeframes,3,model,trade=True,
                         confirmed_chart=confirmed_chart,live_confirmed=live_confirmed,timeout=timeout)
