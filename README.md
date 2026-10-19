# Trade With AM — Price Action Trading Agent

## [Install with ChatGPT — Step-by-Step](INSTALL-WITH-CHATGPT.md)

**Start here:** [TradingView MCP installation video](https://youtu.be/Qc6d5M-RPGc)
· [Trade With AM YouTube channel](https://www.youtube.com/@TradeWithAMTrading/videos)

A Windows desktop app that uses your installed Codex CLI and TradingView MCP
connection to analyze support/resistance and conditional price-action setups.
It draws on TradingView, verifies drawings and Object Tree groups, and can send
setup explanations to your Telegram destination.

This project is intended to be free and open-source under [MIT](LICENSE).
External services may require accounts, subscriptions or paid AI usage.
**The app does not place trades or provide real-money automated execution.**
Analysis can be wrong; a conditional setup is not a guaranteed signal.

**Publication status:** the first public repository/release is being prepared
locally. The intended repository is `tradewithamofficial/Price-Action-Trading-Agent`.
No repository or release was published by this preparation step. No online release
download URL is claimed here.

## Features

- **Find Support And Resistance Levels:** combines selected timeframes into lines
  or zones; defaults to three supports and three resistances in total, grouped as
  **Support and Resistance Levels**.
- **Find Trade Setups:** considers up to three conditional ideas with entry,
  confirmation, invalidation and targets. Verified annotations belong to **Price
  Action Setup 1**, **2** and **3** as needed. **NO TRADE / WAIT** is a valid result.
- Live selected-watchlist retrieval, clearly labeled fallback symbols and a model
  dropdown sourced from the local Codex catalog. Listing is not an access check.
- Exact symbol selection on the approved chart after explicit confirmation,
  followed by identity, candlestick, drawing and group verification.
- Telegram HTML explanations with exact price text and confirmation conditions,
  destination/acknowledgement checks and no automatic resend.
- Dark CustomTkinter UI/dialogs, robot icon, transparent illustration, always-visible
  progress and retained logs controlled by **Show Status**.

## Requirements

1. **Windows x64.** The package was built and checked on Windows 10; other systems
   and installations have not been validated.
2. **TradingView Desktop**, signed in and running with your existing supported
   debugging setup on **port 9222**. Use one dedicated saved chart tab with one
   standard candlestick pane.
3. The **existing TradingView MCP connector**, its dependencies and **Node.js**.
   Verify your Codex-to-TradingView connection first using the
   [MCP tutorial](https://youtu.be/Qc6d5M-RPGc). The connector is not bundled here.
4. **Codex CLI**, installed and signed in, with account access to the selected
   model. Astra is preferred when listed; availability depends on your installation.
5. Your own Telegram bot and numeric destination chat ID for trade-setup delivery.

Supply your own accounts and comply with the external services' terms. The MIT
license covers project code, not external services or their charges.
**Python and PyCharm are not required for the packaged Windows app.** Python is
needed for source runs/builds; Python 3.14 is the locally tested series. Tkinter
must be available in that Python installation. PyCharm is optional.

## Windows release: download and run

After the maintainer publishes the repository, open its **Releases** section and
download the official Windows distribution asset. Do not guess an EXE download URL.
If no release exists yet, use the source instructions below.

1. Extract the complete distribution to a writable folder, such as Documents.
2. Keep **all** files together, especially `_internal`.
3. Double-click **PriceActionTradingAgent.exe**.
4. Configure your private Telegram file below before using setup delivery.

This is a **one-folder**, windowed Windows x64 app, not a single portable EXE or an
installer. Its Python/UI runtime and public assets are included. Codex, Node.js,
TradingView and the MCP connector remain external. Missing Telegram configuration
does not prevent GUI startup, but setup delivery reports an error until configured.
The EXE is unsigned; follow normal Windows security policy rather than disabling
protections.

The maintainer's local build output is:

```text
release/PriceActionTradingAgent/PriceActionTradingAgent.exe
```

That is a local path, not a download link. See [release setup](RELEASE-SETUP.txt)
and the [publication checklist](docs/RELEASE-CHECKLIST.md) for distribution contents
and outstanding checks.

## Run from Python source

After publication, use GitHub **Code → Download ZIP**, or clone the actual
repository URL shown by GitHub. Extract/open the source folder. In PowerShell:

```powershell
# Replace this example with the folder you downloaded or cloned.
Set-Location 'C:\path\to\Price-Action-Trading-Agent'
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Reuse an existing environment if already installed. Obtain Python from
[python.org](https://www.python.org/downloads/windows/) if needed. Do not install
another trading framework or copy another user's Codex/TradingView profile.

## Telegram: keep credentials local

For source runs, work beside `main.py`. For the Windows package, work beside the
EXE, **outside** `_internal`. Copy the public template without overwriting an
existing private file:

```powershell
if (-not (Test-Path -LiteralPath telegram_config.local.json)) {
    Copy-Item -LiteralPath telegram_config.example.json -Destination telegram_config.local.json
}
```

Edit the private copy locally. Fill `bot_token` with your bot token and `chat_id`
with the exact numeric destination ID **as a quoted JSON string**. The bot must
be permitted to send there; username aliases are rejected. Never paste either
value into ChatGPT, Codex, GitHub, screenshots or logs. Never commit or distribute
`telegram_config.local.json`.

**Find Trade Setups attempts Telegram delivery after analysis.** S/R does not send
Telegram. Failure preserves the final explanation in the existing Copy/Close
results popup, without repeating AI analysis or automatically resending messages.
Incomplete chart verification is reported as unverified even when Telegram accepts
it. API acceptance does not prove a person read the message.

## Use the application

1. Start your working TradingView debugging/MCP setup on one dedicated saved
   candlestick chart. Do not change charts during analysis.
2. Select a **full exchange-qualified symbol**, for example `BYBIT:XAUUSDT.P`.
   Bare/approximate aliases such as `BYBIT.P` are not exact targets.
3. Choose timeframes (defaults: 1H, 4H, 1D), S/R levels per side and an available
   model. Leave **All Charts** unchecked.
4. Click an analysis button and review **OK / Cancel**, including any actual
   FROM → TO symbol switch. Cancel blocks switching, analysis and Telegram delivery.
5. Wait for verification; use **Show Status** to inspect retained logs. Progress
   stays visible while logs are hidden. Review warnings before requesting another run.

Dropdown selection and Refresh alone never change the chart. The selected symbol
remains displayed after a switch; there is no automatic switch back.

## Limitations

- **All Charts / multi-chart iteration is unimplemented** and blocks both buttons
  when selected. There is no six-agent controller, scheduling, exchange-account
  connection or order placement.
- Model access, MCP approval policy and TradingView private APIs can change. A
  stale/missing catalog or required approval can block execution safely.
- Existing named groups or ambiguous ownership require operator review. Old
  groups/drawings are not automatically adopted, refreshed or deleted.
- Timeouts and verification failures may leave partial drawings/groups. There is
  no automatic rollback/retry. Telegram timeout outcomes can be uncertain; inspect
  the destination before any manual resend.
- Only the maintainer's local Windows setup has been checked. Offline tests do
  not establish AI analysis quality or guarantee external-service behavior.

## Technical docs, bugs and contributions

The [technical guide](docs/TECHNICAL.md) preserves connection/discovery, permissions,
identity/ownership verification, grouping, Telegram safeguards, offline testing and
build details. Avoid unrestricted test discovery: a legacy test reads a live watchlist.

After publication, use the repository's **Issues** tab for bugs and feature requests.
Include version, Windows version, reproduction steps, expected/actual behavior and
sanitized errors. Remove secrets, private paths, chat/account data and run records.
Use [SECURITY.md](SECURITY.md) for sensitive reports.

Contributors can fork the project, make a focused feature branch, run relevant
offline tests and submit a pull request for maintainer review. See
[CONTRIBUTING.md](CONTRIBUTING.md). Execution, credential and verification changes
need careful review.

## Roadmap

Proposed directions, without promised dates: improve beginner setup/troubleshooting,
expand offline coverage, improve verified drawing lifecycle handling, and evaluate
further analysis/UI improvements. Multi-chart analysis and other integrations need
separate design/review and are not current features. Autonomous real-money trading
is not supported.

## License and acknowledgements

Project code: [MIT](LICENSE), copyright **2026 Trade With AM**, confirmed by the
owner. The owner also authorizes the two supplied AI-generated UI images under
MIT to the extent the owner holds applicable rights. Dependencies and their
artwork retain their own licenses: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
See the [release checklist](docs/RELEASE-CHECKLIST.md) and
[final audit](docs/FINAL-RELEASE-AUDIT.md) for permission evidence and distribution scope.

Tutorials and updates: [Trade With AM on YouTube](https://www.youtube.com/@TradeWithAMTrading/videos).
