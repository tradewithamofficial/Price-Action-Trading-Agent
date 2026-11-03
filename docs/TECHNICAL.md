# Technical guide

[Back to README](../README.md)

## Direct Codex workflow (v1.1.0 candidate)

The existing window, confirmations, background workers and discovery utilities
remain in place. The two buttons load editable analytical instructions:

| File | Used by |
| --- | --- |
| `reference_simple/support_resistance.txt` | Find Support And Resistance Levels |
| `reference_simple/price_action.txt` | Find Trade Setups, including classical chart patterns |
| `reference_simple/main.py` | Preserved reference runner; not the GUI entry point |

The supplied analytical files are preserved. At the default settings their full
text is sent to Codex, followed by the approved exact chart identity and preservation
instructions. Both require **1H, 4H and 1D together**; other combinations are
rejected rather than silently ignored. The S/R count control replaces only known
count/label phrases for non-default counts. An edited file with missing count
markers must use the default count or restore the markers. Setup analysis does
not use the S/R count control. All Charts remains blocked.

`sr_agent.py` calls the installed CLI once, with UTF-8 stdin:

```text
codex exec --model <selected-model> --sandbox read-only --skip-git-repo-check --output-last-message <unique-final-response.txt> -
```

There is no output schema, final JSON contract, Python pricing engine or
application-side group creation. Codex uses the existing TradingView MCP setup
to analyze, draw and group. The app does **not** inject an enabled-tool list or
auto-approval configuration. The inherited MCP configuration governs available
tools and approvals; the filesystem sandbox does not authorize MCP calls.
Noninteractive approval cannot ask an operator a new question. A required approval
stops the workflow, with no bypass, permission escalation or automatic retry.
Prompt instructions prohibit orders, existing-object changes and credential access;
they are not an independent tool-level permission boundary. Use a suitably scoped,
working Codex/MCP configuration before approving analysis.

The final response comes only from `--output-last-message`, never stdout/tool logs.
Each request saves `responses/<unique-run-id>/final-response.txt` beside the source
or EXE; sanitized diagnostics and available chart readbacks stay in that private
run folder. Failed/timeout partial responses are retained and marked incomplete.
Nonzero exits, empty final output, tool-approval denials and recognized tool-access
failures are not successful analysis. Exit zero alone does not verify chart results.

## Discovery and exact chart confirmation

Codex discovery checks PATH and `%APPDATA%\npm\codex.cmd`, resolving the npm shim
to its installed native executable. Node discovery also checks standard Windows
installation folders. Its directory is added to the child PATH, without changing
the global environment. Frozen startup resets the bundle DLL search override
before launching external Node/Codex. No PyCharm working directory is required.

| Environment variable | Purpose |
| --- | --- |
| `SR_CODEX_PATH` | Installed Codex executable or supported npm launcher |
| `SR_NODE_PATH` | Full path to installed `node.exe` |
| `SR_TRADINGVIEW_MCP_DIR` | Existing connector directory |
| `CODEX_HOME` | Existing Codex directory, normally `%USERPROFILE%\.codex` |
| `SR_SYMBOLS` | Exact fallback symbols, comma-separated |

The default connector is `%USERPROFILE%\tradingview-mcp`. Watchlist Refresh runs
its read-only `watchlist get` in a background worker with a 25-second timeout.
Unavailable or empty results are clearly labeled Fallback. Refresh never selects
a chart. Models come from the local Codex catalog, not an analysis probe; listed
does not mean account access has been confirmed.

Both buttons inspect one saved dedicated chart with one standard candlestick pane.
The short dark confirmation discloses any actual FROM → TO symbol change. Cancel,
Escape and X prevent analysis, symbol switching and Telegram delivery. After OK,
`ensure_selected_symbol()` rechecks the approved chart and uses the existing
connector `setSymbol` only when needed. Its existing render-wait helper and exact
destination, tab, URL, chart, layout, pane and candle checks must pass. No aliases,
tab switching, automatic recovery or switch back to the old symbol are allowed.

## Read-only drawing verification

`sr_grouping.py` now contains only the shared lock and fixed read-only snapshots.
The app can independently read the approved chart's drawing IDs, points, properties,
group names/memberships, studies and resolution. It never creates or repairs a group.

Before/after comparison requires all existing drawings, groups and study records
to remain unchanged and the original timeframe to be restored. New grouped objects
must exist in the readback and belong exclusively to new groups; old IDs cannot be
adopted. The S/R group is **Support And Resistance Levels**, as spelled in the supplied
prompt. Setup groups use **Price Action Setup 1**, **2**, **3**, or the prompt's
distinct-name alternative when existing names are occupied. Existing memberships
are never silently accepted as changed. Labels and colors do not prove ownership.

Readback availability is separate from plain analysis completion: if an API is
unavailable, the complete response can still be displayed, but drawings remain
explicitly **unverified**. A readback mismatch never triggers repair, retry,
deletion or regrouping. A clear NO VALID SETUP with no chart changes can be verified
as a no-drawing outcome. These checks corroborate chart objects and preservation;
they do not establish analytical correctness or trade outcomes.

The historical shared lock remains under
`%LOCALAPPDATA%\TradeWithAM\SupportResistanceAgent\runs\analysis.lock`, preventing
overlap between app instances. After a crash, inspect the chart and close all app
instances before removing a genuinely stale lock. Old private records are not
replayed or treated as ownership evidence.

## Results, Telegram and UI

Both buttons display the entire human-readable final answer in the existing
Copy/Close results window. S/R success requires independent drawing/group readback.
Trade setup delivery uses a small plain-text adapter: it sends the complete final
answer, escaped as Telegram HTML with symbol, timeframes and timestamp. No setup
parser discards classical-pattern analysis, prices or confirmation conditions.

The existing structured formatter remains compatible with its offline fixtures;
the direct workflow uses the complete-response formatter. Formatting finishes
before HTTPS: conservative 4096 raw-HTML UTF-16 units per part, balanced escaped
HTML and at most 20 parts. Oversized reports fail rather than being truncated.
Transport still checks TLS, redirects, response bounds and matching acknowledgements
(HTTP 200, ok, exact destination, positive unique message ID and parsed text).
Accepted parts are not automatically resent. API acceptance does not prove reading.
Failed/blocked execution is not delivered. Unverified chart results carry a warning
if a completed response is sent. Missing configuration does not block GUI startup.

Private Telegram configuration stays beside `main.py` or the EXE, outside `_internal`.
Never publish it. It is read only by delivery, not inserted into Codex's input.
Background workers, modal consent, duplicate-job protection, progress updates,
Show Status log retention, dark theme, robot icon and illustration are unchanged.

## Offline tests and Windows build

From the source folder, with the existing build requirements installed:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_direct_analysis tests.test_grouping tests.test_mcp_approval tests.test_prompt_styles tests.test_preservation_diagnostics tests.test_telegram_sender tests.test_trade_setups tests.test_symbol_selection tests.test_status_visibility tests.test_dark_ui tests.test_dark_dialogs tests.test_agent_image tests.test_packaging tests.test_repository_release -q
```

These suites mock services. GUI tests need a Windows desktop. Some symbol-helper
tests execute fake connector modules with Node.js; they never contact TradingView.
The obsolete packaged test that read a real watchlist has been removed.

Run `.\build.ps1` for the existing pinned PyInstaller **one-folder/windowed** build
with the official CustomTkinter/Pillow hooks. The candidate output is
`release/v1.1.0/PriceActionTradingAgent/PriceActionTradingAgent.exe`.
Both analytical files ship beside the EXE in `reference_simple` for editing and
inside `_internal/reference_simple` as bundled resources. The external folder takes
precedence; a missing file in that folder is an error, not a hidden fallback.
If the external folder is absent, bundled resources are used. The reference Python
runner stays in source only. The build generates a blank public Telegram example
and retains the icon, illustration, setup instructions and all license notices.
Private responses/configuration are not bundled; previous v1.0.0 assets are retained.

After building:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_release -q
```

Release tests inspect the actual archive and resources, exercise the archived GUI
with services mocked, and launch the idle EXE with unavailable connector/CLI paths
and a synthetic catalog. They do not run AI, mutate charts or send Telegram.

References: [CustomTkinter packaging](https://customtkinter.tomschimansky.com/documentation/packaging/),
[PyInstaller external programs](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application),
[MCP tutorial](https://youtu.be/Qc6d5M-RPGc).
