# Contributing

Thank you for helping improve Trade With AM — Price Action Trading Agent.
The intended repository is `tradewithamofficial/Price-Action-Trading-Agent`;
publication is pending. Follow these steps once the repository is available.

1. Fork the repository and clone your fork.
2. Create a feature branch, for example `git switch -c improve-status-text`.
3. Make a focused change and explain the problem it solves. Preserve the current
   GUI/core separation and avoid adding dependencies without a clear need.
4. Install the documented environment and run the relevant **offline** tests.
5. Check your diff and staged files for secrets, local paths, chart/account data
   and generated artifacts. Never force-add ignored files.
6. Submit a pull request describing behavior, validation, limitations and risks.
   Use the supplied pull-request template, then wait for maintainer review.

## Development and offline tests

On Windows, from the source folder, using Python 3.14 (the tested series):

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest tests.test_repository_release tests.test_dark_dialogs tests.test_dark_ui tests.test_status_visibility tests.test_agent_image tests.test_trade_setups.SetupGuiTests tests.test_symbol_selection.SelectionGuiTests tests.test_telegram_sender.TelegramGuiTests tests.test_prompt_styles tests.test_release.SourceIconTests -v
```

This explicit suite uses mocked services. Do **not** run unrestricted test discovery:
the legacy `tests.test_packaged_gui` reads a live TradingView watchlist. Additional
offline core suites and build checks are described in [the technical guide](docs/TECHNICAL.md).
Real UI tests require a Windows desktop session. Some core tests also need Node.js
to execute fake connector modules; those tests do not connect to TradingView.

Do not run AI analysis, change charts, send Telegram messages or contact trading
accounts as part of an ordinary pull request. Any live test needs separate,
explicit operator authorization. Never add credentials to fixtures or screenshots.

## Changes that need extra review

Maintainers must carefully review execution/approval policy, chart identity,
drawing ownership and preservation, symbol selection, credentials, Telegram
transport, dependencies and packaging changes. Trading execution is **not** a
current feature; do not enable order placement or account access incidentally.
Include negative tests showing that cancellation and verification failures still
stop subsequent operations. Do not weaken safeguards to make a test pass.

Only contribute work you have the right to distribute. Project-code contributions
are intended to be under [MIT](LICENSE); preserve all third-party notices and
declare any imported/adapted code or artwork and its license.

## Recommended branch protection (maintainer action after publication)

Protect the default branch, normally `main`, with pull requests and maintainer/code
owner review; dismiss stale approvals and resolve review conversations. Disable
force pushes and branch deletion. Add required offline CI checks **after** a
working workflow exists; this preparation does not create CI or configure GitHub.
CODEOWNERS alone does not enforce review. A PR author cannot approve their own PR,
so choose an independent eligible reviewer before enforcing approvals for the sole
maintainer's own changes. Apply restrictions to administrators when practical and
keep any emergency bypass deliberate and documented. See
[GitHub's protected-branch documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
