# Technical guide

[Back to README](../README.md)

These notes describe the existing implementation; they do not authorize live
operations. The GUI/core separation and application behavior are unchanged.

## Modules and environment

| File | Responsibility |
| --- | --- |
| `main.py` | CustomTkinter GUI, confirmations, background jobs and outcomes |
| `sr_agent.py` | Prompts, discovery, chart identity, Codex invocation and results |
| `sr_grouping.py` | Fixed snapshots/grouping operations and ownership verification |
| `telegram_sender.py` | Formatting, private config, HTTPS delivery and acknowledgements |
| `ui_dialogs.py` | Reusable dark modal dialogs |
| `build.ps1` | Windowed one-folder PyInstaller build and public release resources |

The locally tested runtime is Python 3.14.7 / Tcl-Tk 9.0.4, CustomTkinter 6.0.0 and
Pillow 13.0.0. Build versions are pinned in `requirements-build.txt`. The connector
normally lives under `%USERPROFILE%\tradingview-mcp`; the app never installs it.

## Discovery, watchlist and models

Codex discovery checks PATH and `%APPDATA%\npm\codex.cmd`, resolving the npm shim
to its installed native executable. Node discovery also checks standard Windows
installation folders. The discovered Node directory is added to the child PATH
for MCP startup when Explorer's environment is stale. No global setting is changed.
Frozen runs use the EXE directory as their working root and reset the bundle's
DLL search override after Tk starts, before launching external Node/Codex.

| Environment variable | Purpose |
| --- | --- |
| `SR_CODEX_PATH` | Explicit Codex executable or supported npm launcher |
| `SR_NODE_PATH` | Full path to installed `node.exe` |
| `SR_TRADINGVIEW_MCP_DIR` | Existing connector directory |
| `CODEX_HOME` | Existing Codex directory, normally `%USERPROFILE%\.codex` |
| `SR_SYMBOLS` | Comma-separated exact symbols for the labeled fallback list |

Set overrides only for nonstandard installations and restart the app. Explicit
missing executables fail rather than being silently replaced.

Startup/Refresh uses the existing connector CLI's `watchlist get`, backed by MCP
`watchlist_get`'s core reader. This background read has a 25-second subprocess
timeout. It may open the watchlist panel but does not select a symbol/timeframe or
create drawings. Empty/malformed/unavailable responses show the configured list
as **Fallback**; actual entries are never mixed with invented symbols.

Models come from `CODEX_HOME\models_cache.json`, excluding hidden/internal entries.
Astra is preferred if listed. Entries are **access untested**; no AI invocation
populates the dropdown. A missing catalog gives an error, not invented choices.
Open your installed working Codex session to populate its catalog, then Refresh.

## Confirmation and symbol selection

Both buttons share `ensure_selected_symbol()`. A background preview identifies
one saved chart tab and one candlestick pane before the short confirmation
discloses any actual symbol change. Cancel, Escape and X reject. No analysis,
chart switch or Telegram delivery follows rejection.

After OK, the fixed helper rechecks the approved source and uses the existing
`chart_set_symbol` / `setSymbol({symbol})` on that active chart. A matching symbol
makes no setter call. Validated JSON input is not interpolated executable code.
Full exchange-qualified symbols are required.

The existing `waitForChartRender()` readiness check must pass, followed by exact
destination/candlestick/tab/chart/layout/pane checks and another strict application
verification. A header alias or setter success flag is insufficient. Loading
failure may already have switched the symbol; the app stops without switching
tabs or attempting recovery. The selected symbol is not automatically switched back.

## Invocation-only MCP permissions

Codex receives the selected model, `--sandbox read-only`, `--skip-git-repo-check`,
`--color never`, `--output-last-message` and a stdin prompt. The nine-tool list is:

```text
chart_get_state, tab_list, pane_list, chart_get_visible_range,
data_get_ohlcv, chart_set_timeframe, draw_shape, draw_list, draw_get_properties
```

The app supplies invocation-specific `mcp_servers.tradingview.enabled_tools` and
per-tool `approval_mode="approve"`. Noninteractive `never` approval cannot collect
new prompts; managed or disabled-tool restrictions can still block execution.
The filesystem sandbox is separate from MCP chart permission. No global config
or connector source is edited.

Astra has no unrestricted `ui_evaluate`, symbol/tab switching, drawing deletion,
indicator changes or order/account capability. Separate application-controlled
helpers use fixed validated operations through the existing connector. Failures
never broaden permissions. There is no automatic AI retry.

## Drawing ownership, preservation and grouping

S/R prompts allow horizontal lines for precise levels and rectangles for meaningful
zones, with red resistance and green support. Counts combine selected timeframes.
Visible labels contain prices/ranges and timeframe confluence. Labels/colors alone
are not ownership proof.

Before Codex starts, the app snapshots the approved target, drawings, groups,
indicators and original timeframe. Codex must return final JSON containing the
application run ID, exact target, completion status, new IDs, roles, geometry and
styles. Final content comes from the final-message file, never substituted with
stdout/tool logs. Exit code zero or model assertions do not prove chart success.

Independent snapshots verify the new IDs/points/properties/counts, restored
timeframe and preservation of existing objects. Only then does the fixed helper
use `shapesGroupController()` methods including `createGroup(newIds)` and
`setGroupName` on verified new objects. Another snapshot checks exact group name,
membership and preservation again.

Only **Support and Resistance Levels**, **Price Action Setup 1**, **Price Action
Setup 2** and **Price Action Setup 3** are accepted. Existing name collisions stop
for operator review even if records exist. There is no automatic adoption,
refresh, overwrite, deletion or regrouping of old objects. Partial failures leave
objects intact, stop later grouping and do not trigger automatic retry/rollback.

Setup analysis considers structure, continuation, breakout/retest, pullbacks,
failed breakouts and confirmation. Fewer than three setups or WAIT is valid.
Existing S/R drawings are read-only context. Setup annotations include entry,
confirmation, invalidation and targets; blue/purple/orange distinguish groups.
The results Copy/Close popup contains only the final human explanation.

Private JSON ownership/run records live under
`%LOCALAPPDATA%\TradeWithAM\SupportResistanceAgent\runs`. That historical internal
folder name intentionally remains unchanged. Records hold target identity,
IDs/readbacks, group IDs, times and verification outcomes. They are not ownership
proof without current chart checks. An exclusive `analysis.lock` prevents overlap.
After a crash, an operator must inspect charts/records and close all app instances
before removing a genuinely stale lock. Never remove one to bypass an active job.

## Telegram and UI outcomes

Private config lives beside `main.py` or the EXE, outside `_internal`. It is read
only by delivery after Codex exits, never included in AI prompts/arguments. The
public example has two blank strings; numeric chat IDs remain quoted exact strings.

Telegram HTML uses the title **TRADE WITH AM — PRICE ACTION TRADING AGENT**,
symbol, timezone-aware timestamp, timeframes and ranked LONG/SHORT setups with
strategy, reasoning, entry, confirmation, invalidation and targets. Exact price
text, escaping and safety conditions survive without a duplicated full assessment.
WAIT uses the actual final reason. Each part ends with the conditional-setup line.

Formatting finishes before HTTP. Limits are conservatively 4096 raw-HTML UTF-16
units per part and 20 parts, with balanced HTML and readable boundaries. Oversized
reports fail instead of being truncated. HTTPS verifies TLS, bounds responses,
rejects redirects and has a default 10-second timeout per part. Acknowledgements
must match HTTP 200, `ok: true`, destination, new positive message ID and parsed text.

Analysis, chart verification and delivery remain separate outcomes. S/R success
needs drawing/group verification; setup success also needs required Telegram
acceptance. Unverified chart results retain a warning even if sent. Failure
preserves the final-analysis popup and sanitized diagnostics. No accepted part
is resent automatically. Duplicate analysis identities are blocked within the
session; there is no startup replay, persistent resend queue or read guarantee.

Background jobs preserve GUI responsiveness and prevent overlap. Progress/status
always remains visible. Show Status controls only retained technical logs, heading
and scrollbar. Confirmations/simple outcome dialogs are dark; the results popup
remains standard Tkinter. The illustration preserves alpha/aspect ratio and is
skipped if unreadable. Assets resolve relative to the module, including a bundle.

## Offline tests and builds

From the source folder with `requirements-build.txt` installed:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_repository_release tests.test_dark_dialogs tests.test_dark_ui tests.test_status_visibility tests.test_agent_image tests.test_trade_setups tests.test_symbol_selection tests.test_telegram_sender tests.test_grouping tests.test_preservation_diagnostics tests.test_mcp_approval tests.test_prompt_styles tests.test_packaging -v
```

Services are mocked and fixed helper operations use fake connector/chart modules.
Node.js is needed for helper tests. GUI tests require a Windows desktop session.
Do not use `unittest discover`: legacy `tests.test_packaged_gui` reads a live watchlist.

After building, `tests.test_release` checks the bundle/resources/icon and extracted
GUI code, then launches/closes its own idle EXE child using missing connector/Node/
Codex paths and a synthetic model catalog. It does not call live services:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_release -v
```

Build with `.\build.ps1`. It locates paths relative to itself and uses pinned
PyInstaller **`--onedir --windowed`** with official CustomTkinter/Pillow hooks.
Output is `release/PriceActionTradingAgent/PriceActionTradingAgent.exe`, `_internal`,
blank config, setup instructions and license/notice files. Only the public ICO/PNG
are explicitly added as UI data. Private config or a populated example stops the
build. Generated specs/caches stay in `build/`; reviewed ZIPs belong in GitHub
Releases, not the source repository.

Step 542's EXE was 3,485,420 bytes; its 91-file distribution before adding license
materials was 42,428,071 bytes. Startup and 62 unique offline checks passed then.
That is local historical evidence, not a guarantee for another computer. See the
[current publication checklist](RELEASE-CHECKLIST.md).

References: [CustomTkinter packaging](https://customtkinter.tomschimansky.com/documentation/packaging/),
[PyInstaller external programs](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application),
[MCP tutorial](https://youtu.be/Qc6d5M-RPGc).

Core prompt builders remain reusable without the GUI. Unconfirmed analysis-runner
calls return `confirmation_required`; any future caller still needs explicit
per-request consent and the verified target. No six-agent controller is included.
