# Security and privacy

## Reporting a vulnerability

Never post a token, private chat ID, authentication file, unredacted run record,
chart/account screenshot or exploit containing private data in a public issue.
Once the repository is published, use **Security → Report a vulnerability** if
GitHub private reporting is enabled. Otherwise open an issue containing only a
request for a private reporting channel, without sensitive details, and wait for
the maintainer. No private email address or response deadline has been established.
Private reporting must be configured before advertising it as available.

## Local files that must stay private

- `telegram_config.local.json` and backups: the bot token and exact destination ID.
- `.env` files, API keys, passwords, private keys and other local configuration.
- Codex authentication, configuration and session/model-cache files.
- TradingView browser profiles, cookies, debug/session data and account details.
- `diagnostics/`, logs and generated ownership/run records, including those in
  `%LOCALAPPDATA%\TradeWithAM\SupportResistanceAgent\runs`.
- Virtual environments, IDE settings and build caches.

The source `.gitignore` excludes these common paths; it cannot remove tracked
files or rewrite history. Review file selection and history before every public
upload. Never upload this entire working folder as a source ZIP. Use a clean,
reviewed source tree; distribute binaries separately through GitHub Releases.

The shareable configuration is `telegram_config.example.json`, containing only
empty `bot_token` and `chat_id` strings. Create your private copy beside `main.py`
for source runs or beside the EXE for packaged runs. Keep it outside `_internal`.
No maintainer needs your real credentials to troubleshoot.

## If a secret was committed or exposed

Stop publication. Revoke/rotate the affected credential through its issuer first;
removing a file or adding `.gitignore` does not invalidate a leaked token. Inspect
all branches, tags and relevant history, clean the affected history using the
hosting provider's documented procedure, and coordinate with anyone holding a
copy. Review forks, release assets, logs and caches too. Rescan before publishing.
Do not paste the secret into an issue or a cleanup command that records it in
shell history. See [GitHub's sensitive-data guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

## Operational boundaries

TradingView debugging on port 9222 and the existing MCP connection can control
charts. Follow the connector's supported local setup; do not expose the debug
port publicly. Keep exact chart/tab/pane checks and explicit confirmation enabled.
The Codex filesystem sandbox does not make MCP chart operations read-only.
This project does not configure an exchange account or place orders.

Reports may contain market information and local target identifiers. Redact logs
before sharing even if the app has already sanitized common credential formats.
Any incomplete drawing/group or Telegram outcome needs operator review before a
new request; there is no automatic retry or rollback guarantee.

## Release scope

Only the current reviewed release is a maintenance target; no supported historical
version matrix is promised. Maintainers should review dependency advisories and
redistribution terms before release. The local preparation audit is recorded in
[docs/RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md); it is not a proof that other
copies or remote Git histories are clean.
