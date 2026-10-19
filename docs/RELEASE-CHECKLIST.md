# Local release preparation and publication checklist

Prepared on **2026-10-19** for the intended repository
`tradewithamofficial/Price-Action-Trading-Agent`. This is a local review document,
not a claim that a repository or release already exists.

## Owner decisions and final audit (Step 544)

- [x] Owner confirmed **Trade With AM** as copyright holder on **2026-10-19**.
  `Copyright (c) 2026 Trade With AM` is unchanged. The owner developed the app with
  ChatGPT/Codex assistance and authorizes its source, including the adapted sender
  from the owner's own AI-Trading-Desk project, under MIT subject to third-party terms.
- [x] Owner confirmed that the robot icon and transparent chart illustration were
  generated with ChatGPT specifically for this project, not downloaded from an
  icon/stock library. Redistribution is authorized under MIT **to the extent the
  owner holds applicable rights**. This is not an independent assertion of
  copyright eligibility or exclusive AI-output rights.
- [x] Native notice review completed using installed-file hashes and versioned
  Python dependency sources. Added the missing mandatory mpdecimal BSD notice,
  plus LibTomMath and xz/liblzma texts; clarified retained Microsoft conditions.
  See [the final audit](FINAL-RELEASE-AUDIT.md) for evidence and mandatory versus
  optional attributions. No native binary was changed or independently re-attested.
- [x] Intended public repository confirmed in Step 544:
  `tradewithamofficial/Price-Action-Trading-Agent`.
- [ ] Choose an initial version/tag and Windows release asset name **before the
  first binary release**. This does not block the first reviewed source commit.
  No version, release URL or download asset is invented.
- [ ] After repository creation, configure private vulnerability reporting and
  sensible branch protection. No GitHub settings or permissions were changed here.

## Local security audit scope

The project and its parent folders have no Git repository marker. `git rev-parse`
reports that this is **not a Git repository**. Consequently no local index,
branches, tags or commit history exist here to inspect. No conclusion is possible
about other copies, deleted repositories or a remote history. If an existing
history is later imported, audit it before publication; if any suspected credential
appears in history, stop, rotate it and follow [SECURITY.md](../SECURITY.md).

`.gitignore` now excludes private Telegram configuration/backups, environment and
authentication files, browser/session data, diagnostics/run records, IDE files,
virtual environments, Python caches, build/release outputs and unused artwork
originals. Existing private and generated files were left on disk. Ignore rules
are verified using Git in a disposable repository under ignored `build/`; the
working project itself is not initialized or committed by these checks.

The reviewed public source consists of the application modules, build/requirements,
tests, beginner/technical/community documents, public blank configuration template,
public UI assets and third-party license texts. The two included assets have
the owner permission recorded above. Source file selection must be
reviewed before the first commit; never force-add ignored files or upload the
whole working directory through a browser.

The audit checks for common token/key/private-key formats and exact private local
configuration values without recording them in the report. It also checks the
existing distribution and extracted compiled application strings. It is a focused
local inspection, not a complete secret-detection or account-data certification.
Synthetic test fixtures use fake destinations/credentials and are not real account
data. Do not publish diagnostics, even if a particular sample appears harmless.

The executable may retain build-time source filenames inside compiled bytecode.
Generic project/tool paths are not credentials, but build paths cannot be promised
absent. Public documents use generic paths; IDE/build caches with local paths are
excluded. Live chart snapshots and prior analysis/ownership records are not public
source material.

## Confirmed package layout

The existing Step 542 executable is a windowed Windows x64 **one-folder** build:

```text
release/PriceActionTradingAgent/
  PriceActionTradingAgent.exe
  _internal/
  telegram_config.example.json
  README-SETUP.txt
  LICENSE
  THIRD-PARTY-NOTICES.md
  third_party_licenses/
```

The last three license entries are added as release documentation; the EXE is not
rebuilt by this preparation. Future `build.ps1` runs copy them automatically.
The original EXE SHA-256 is
`ded47b593e6a01c0a033194bf6a566676287d15c747bac091bb5e986779fd44a`.
CustomTkinter themes/fonts, Pillow native modules, Python/Tk runtime, public robot
ICO and PNG illustration are present. The only configuration shipped is the
two-field blank Telegram example. Codex, Node.js, TradingView and the MCP server
remain external prerequisites.

## Offline validation

Run the explicit suites in [CONTRIBUTING.md](../CONTRIBUTING.md) and the
[technical guide](TECHNICAL.md); do not use unrestricted discovery. Release
artifact checks can be run without the separate EXE launch:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_release.ReleaseArtifactTests.test_public_resources_runtime_and_blank_example_only tests.test_release.ReleaseArtifactTests.test_windowed_x64_exe_embeds_exact_robot_icon_images -v
```

Local validation passed **148 offline tests**, including all new repository/link
checks, current GUI/core safety regressions and existing EXE icon/resource checks.
The modified build script also passed the PowerShell syntax parser; no EXE was
rebuilt. All local Markdown links in the README/community/technical documents
resolve to existing source files.

The Step 543 audit selected **51 public candidate files**, inspected **106 distribution
files** and recursively checked **11,653 compiled code objects** from the existing
EXE. No unresolved common credential-pattern matches or exact private bot-token/
chat-ID matches were found in those candidates/artifacts. Three token-shaped
binary matches were verified as standard JPEG AC-luminance Huffman tables in
Pillow's unchanged binary, which also matched its installed wheel RECORD hash.
No personal Windows-user filenames were found in the extracted code objects;
generic build paths may still be present. These are scoped findings, not a general
guarantee against unknown secret formats or private financial/account information.

Application-module, private-configuration and EXE hashes were unchanged. Existing
private files and diagnostics were not deleted or moved. Only license/setup
materials were added/updated beside the EXE. A redacted file inventory and audit
details are retained locally under ignored `build/`; they are not release assets.
No live AI analysis, chart operation, real Telegram message or trading-account
access was performed. Nothing was committed, pushed or published.

## Step 544 final status

**PASS — ready for the first reviewed source commit.** Owner confirmation resolves
copyright, the two included UI assets and the adapted sender. The identified
native notice gap is corrected. Current inventory: **55 proposed source files**,
**109 distribution files** and **16 retained license texts**. **7 focused offline
checks passed**; the earlier 148-test application suite was not repeated.
No unresolved secret findings remain in the scoped current scan. Details and
mandatory/optional notices are in [FINAL-RELEASE-AUDIT.md](FINAL-RELEASE-AUDIT.md).
The application code, private config, MIT LICENSE and EXE remain unchanged.

Version/tag selection and GitHub protection/reporting setup are later publication
steps, not unresolved rights or first-commit blockers. No actual index/history
exists yet in this working folder, and nothing has been staged or committed.

## Publishing later: source and Windows users

1. Resolve the decisions above. Recheck candidate files and any actual Git history;
   `.gitignore` is not a history repair. Do not delete local user files to prepare
   source; select only the reviewed public tree.
2. Create the intended public repository only after maintainer approval. Upload
   reviewed source/community/license files, without `.venv`, diagnostics, private
   config, `build`, `dist` or `release`. Developers then use **Code → Download ZIP**
   or clone its real URL and follow [README source setup](../README.md#run-from-python-source).
3. Apply reviewed branch protection and private security-reporting settings. See
   [CONTRIBUTING.md](../CONTRIBUTING.md); CODEOWNERS alone does not enforce approval.
4. Once binary rights/notices and offline package checks pass, ZIP the **complete**
   `PriceActionTradingAgent` release folder, including `_internal`, blank example,
   setup and notices. Upload that ZIP to **GitHub Releases**, not the source tree.
   Windows users extract it and double-click the EXE. They create their own private
   JSON beside the EXE. Do not include a maintainer's copy.
5. Attach the actual source tag/version and checksum to release notes. State that
   the build is unsigned, external software/accounts are needed, and offline tests
   do not guarantee AI predictions or account/model access. Only after publishing
   should documentation link the real release asset.

No repository creation, Git initialization of the working project, commit, push,
release publication or permission grant is performed during this preparation.
