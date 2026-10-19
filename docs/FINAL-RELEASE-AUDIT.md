# Step 544 — final local release audit

Date: **2026-10-19**. Intended repository:
`tradewithamofficial/Price-Action-Trading-Agent`.
Paths below are exact project-relative paths unless stated otherwise.
Application modules, the MIT `LICENSE` and executable were not changed by this audit.

## Owner confirmation

The owner explicitly confirmed the intended attribution **Copyright (c) 2026
Trade With AM**, and authorizes the application source under MIT subject to
third-party requirements. Development used ChatGPT/Codex assistance; the sender
was adapted from the owner's own AI-Trading-Desk project.

The owner states both supplied UI images were generated using ChatGPT specifically
for this project, not obtained from icon/stock sites. Redistribution is authorized
under MIT **to the extent the owner holds applicable rights**. Third-party
libraries/assets retain their own authorship and license requirements.

This records owner statements/authorization, not independent proof of generation
history, exclusive rights or copyright eligibility of AI output. No additional
owner confirmation is outstanding for the two included images or adapted sender
on the evidence supplied in this conversation.

## Artwork and adapted-source inventory

| Exact path | Origin / permission evidence | Attribution and result |
| --- | --- | --- |
| `assets/TradeWithAM_Robot.ico` | Owner: generated with ChatGPT for this project; MIT redistribution authorized to extent of applicable rights | **PASS** — project MIT notice, 2026 Trade With AM; also bundled as `_internal/assets/TradeWithAM_Robot.ico` and EXE icon |
| `assets/Futuristic AI Robot with Breakout Chart.png` | Same explicit owner statement/permission; no independent authorship/license metadata in PNG | **PASS** — same project MIT notice; bundled as `_internal/assets/Futuristic AI Robot with Breakout Chart.png` |
| `assets/TradeWithAM_Robot.png` | Unused local artwork; origin/license not established | **PASS — excluded** from intended Git files and binary; resolve rights only if adding it later |
| `assets/Gemini_Generated_Image_h87vqsh87vqsh87v.jpg` | Unused original; filename is not proof of origin/license | **PASS — excluded**; same boundary as above |
| `telegram_sender.py` | Header names `AI-Trading-Desk/core/telegram_sender.py`; origin file exists locally; owner confirms it is their own earlier project | **PASS** — MIT release authorized; origin header retained; no external license invented |
| `main.py`, `sr_agent.py`, `sr_grouping.py`, `ui_dialogs.py`, tests and build script | Owner's AI-assisted source; external libraries imported and existing connector APIs invoked without bundling connector source | **PASS** on owner authorization/local inspection; no separate copied external implementation identified |

Other bundled artwork/data comes from CustomTkinter, not Trade With AM. Exact
paths under `release/PriceActionTradingAgent/`:

- `_internal/customtkinter/assets/icons/CustomTkinter_icon_Windows.ico`
- `_internal/customtkinter/assets/fonts/CustomTkinter_shapes_font.otf`
- `_internal/customtkinter/assets/fonts/Roboto/Roboto-Medium.ttf`
- `_internal/customtkinter/assets/fonts/Roboto/Roboto-Regular.ttf`
- `_internal/customtkinter/assets/themes/blue.json`
- `_internal/customtkinter/assets/themes/dark-blue.json`
- `_internal/customtkinter/assets/themes/gold.json`
- `_internal/customtkinter/assets/themes/green.json`

The supplied CustomTkinter icon/shapes/theme resources retain its upstream MIT
notice; Roboto retains Google copyright and Apache-2.0 terms. None is attributed
to Trade With AM. No other project artwork is selected for Git or explicitly
added by `build.ps1`. Virtual-environment/build-tool source is excluded from Git;
compiled third-party runtime modules remain in the EXE.

## Dependency results

| Status | Component | Evidence, requirement and resolution |
| --- | --- | --- |
| **PASS** | CustomTkinter 6.0.0 | Actual installed LICENSE is MIT, matching upstream; retained in source/release. Conflicting CC0 metadata does not discard the MIT text. Resource authorship stays upstream. |
| **PASS** | Pillow 13.0.0 and codecs | Full 78,481-byte license bundle retained, including MIT-CMU/codec notices. IJG acknowledgement is explicit; applicable FreeType acknowledgement/text is retained. |
| **PASS** | darkdetect / packaging | BSD / dual-license texts retained; both packaging license choices are supplied. |
| **PASS — corrected** | mpdecimal 4.0.0 | Runtime reports 4.0.0; `_decimal.pyd` matches installed Python; versioned manifest agrees. Added `third_party_licenses/mpdecimal-LICENSE.txt`; BSD binary notice is mandatory. |
| **PASS** | Python 3.14.7 / Tcl-Tk 9.0.4 / OpenSSL 3.5.7 | Python, Tcl, Tk and Apache texts/notices retained. Inspected native files match installed Python copies byte-for-byte. |
| **PASS** | zlib-ng / zlib | Python's manifest identifies zlib-ng 2.2.4 despite compatibility string `1.3.1.zlib-ng`. Tcl separately imports `zlib1.dll` version 1.3.2. Both corresponding notices are retained. |
| **PASS** | LibTomMath / liblzma | Tcl imports LibTomMath, whose license in Python's Tcl source is a public-domain dedication/permission text. Python's manifest lists xz 5.2.5, whose liblzma is public domain. Both texts retained; standalone LibTomMath DLL version is not advertised. |
| **PASS — conditions retained** | Microsoft runtime | Unmodified Windows components and Python's additional Microsoft Distributable Code conditions retained. Windows-only distribution; no endorsement or project-MIT relicensing of Microsoft portions claimed. |
| **PASS** | Roboto | Embedded font records identify Copyright 2011 Google Inc., Apache-2.0; full Apache text/attribution retained. |
| **PASS** | PyInstaller 6.22.3 / hooks | Bootloader exception allows the chosen application license subject to dependency terms. No credit/license inclusion is mandatory solely because it generated this bundle; COPYING/hooks texts remain for transparency and applicable runtime portions. |

Native-version evidence:
[Python 3.14.7 build manifest](https://github.com/python/cpython/blob/v3.14.7/PCbuild/get_externals.bat),
the corresponding versioned `python/cpython-source-deps` license files, runtime
reports and byte comparisons to the installed Python copies. This is not
independent cryptographic verification of the Python supplier.

**Mandatory:** retain project/third-party MIT/BSD/MIT-CMU copyright, permission and
disclaimer texts; Tcl/Tk and Python terms; applicable Apache-2.0 terms/attributions;
Pillow codec notices and applicable FreeType binary acknowledgement; Microsoft
runtime conditions. These are present in the reviewed release.

**Optional acknowledgements:** PyInstaller credit for an unmodified generated
bundle under its exception; public-domain LibTomMath/liblzma credit; zlib binary
acknowledgement. Texts are retained anyway. Optional credit does not make other
components' mandatory notices optional.

Complete mappings/source links: [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md).
Three new license texts are copied beside the existing EXE; future builds already
copy the whole notice folder. No EXE rebuild or feature change is needed.

## Intended first commit and release safety

**PASS:** the Git-derived proposed list contains application modules/tests, public
documents, requirements/build script, MIT/community/third-party notices, the blank
Telegram example and only the two authorized project UI assets.

Excluded: private Telegram config/backups, secrets/auth/session files, `.env`, run
records, diagnostics, `.idea`, `.venv`, Python caches, build/dist/release outputs
and unused artwork originals. Real config was not changed, printed or packaged.
Only the blank example ships. Common-secret/known-private-value checks inspect
compiled code as well as visible files.

There is no `.git` repository, staged index or history in this working project.
The list is proposed, not an actual staged commit. Git selection is checked using
a disposable repository under ignored `build/`. Any history imported later needs
a separate history audit. Local redacted audit details and a concrete proposed
file list are retained under ignored `build/`, not intended as release assets.
No universal secret-format, account-data or vulnerability certification is claimed.
Never force-add ignored files.

## Focused validation results

- **7 focused checks passed:** all five repository/documentation/ignore checks
  and the existing release resource/notice and executable icon checks. The full
  148-test application suite was not repeated.
- Current Git-derived proposed source list: **55 files**. Current reviewed binary
  folder: **109 files**, including **16 license texts**. Source/release notices
  agree byte-for-byte; the public Telegram example remains blank.
- Scoped scan: **11,653 compiled code objects**, selected source and distribution
  files checked; no unresolved secret patterns or exact private-config value
  matches. The three previously identified JPEG-table false positives remain
  verified against Pillow's wheel RECORD and standard Huffman table data.
- Concrete local review files: `build/step544-first-commit-files.txt` and
  `build/step544-audit.json`. Both are ignored and contain no secret values.
- Application modules, private configuration, project LICENSE and EXE are
  unchanged. Only documentation/notice files were added or updated.

## Readiness

**PASS — ready for the first reviewed public source commit on the evidence above.**
No owner-confirmation or identified missing-notice blockers remain. Repository
creation/commit/publication still needs later authorization. Choose a version/tag
and asset name before the binary release; configure branch protection/private
security reporting after repository creation. Those later operations do not block
this local source-file review.

Only focused documentation/ignore/license/artifact checks are repeated in Step
544; the 148-test Step 543 application result remains the baseline. No Astra,
chart/Telegram interaction, account access, feature change, commit, push,
repository creation or publication is performed.
