# CHANGELOG — MagicLight Auto

All significant changes are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## v2.0.5 — 2026-04-23

### Changed
- **Rollback to Monolithic Architecture:** Reverted the experimental multi-file module refactor (dashboard, generator, processor, etc.) back to the inherently stable, unified `main.py` standalone structure. The fractional architecture introduced untraceable runtime imports and instability across functions, which have now been fully resolved.
- Added `Process_D_Link` as the 22nd column officially in `SHEET_SCHEMA` to fix the missing column schema warning.

### Documentation
- `README.md` version badge updated to `v2.0.5`.
- Updated `SHEET_STRUCTURE.md` to reflect the extended 22 column architecture including `Process_D_Link`.

## v2.0.4 — 2026-04-22

> **Patch release.** No new features. No structural changes. GitHub Actions workflow and dashboard in development — version held at patch level until those are complete.

### Removed (Dead Code)
- `import gdown` (line 55) — imported but never called anywhere in the codebase. Removed from `main.py` and `requirements.txt`.
- `LAYER_COLS` dict — defined at module level but never referenced by any function. Removed.
- `_show_table()` helper function — defined but had zero call sites. Removed.

### Fixed
- **Temp-file memory leak** — `os.path.exists(temp_video_path)` was comparing a `NamedTemporaryFile` *object* instead of its `.name` string; temp `.mp4` files uploaded to Drive were never deleted. Fixed to `os.path.exists(temp_video_path.name)` and `os.remove(temp_video_path.name)`.
- **Auth bare `except:`** — two bare `except:` blocks in `_get_oauth_credentials()` and `_get_credentials()` could silently swallow `SystemExit` / `KeyboardInterrupt`. Changed to `except Exception:` in both locations. Logic unchanged.

### Documentation
- `README.md` version badge updated `v2.0.3` → `v2.0.4`.
- `CHANGELOG.md` v2.0.3 notes corrected to reflect that dead-code removal and bug fixes were applied in *this* patch rather than deferred.

### Notes
- GitHub Actions workflow not yet configured — `--loop` / `--headless` modes tested locally only.
- Dashboard (`index.html` / `Code.gs`) under active development — no pipeline logic changes made.
- `Process_D_Link` column still not in `SHEET_SCHEMA` — deferred to next release once column is confirmed in production sheet.

---

## v2.0.3 — 2026-04-22

### Added
- `check_all_accounts_credits()` function — iterates all accounts from `accounts.txt`, logs in to each and records their credit balance to the **Credits** Google Sheet tab.
- `--check-credits` CLI flag to trigger the above from the command line without entering the interactive menu.
- Menu option **4 — Check Account Credits** in the interactive console menu.
- `_show_status_table()` helper — renders a rich configuration status table at CLI startup showing email, sheet ID, drive, headless, debug, and local-output states.
- Enhanced `parse_args()` with emoji-annotated help strings and a fully formatted `--help` banner (version, modes, feature list).
- `run_once` / `LOOP_RUN_ONCE` environment variable support for single-cycle loop execution (useful for GitHub Actions scheduled runs).
- Graceful `DRIVE_ONLY_MODE` env variable path — auto-set on GitHub Actions in `--loop` mode; triggers local file cleanup after Drive upload.

### Updated
- **Login flow** (`login()`): added three-attempt navigation retry, email/password fill verification, post-login logout-button check, and credit-selector wait with fallback warning.
- **Account rotation** in `_run_pipeline_core()`: clean context teardown before switching; per-rotation login retry (2 attempts); credit verification of new account before proceeding.
- **Sheet updates** (`update_sheet_row()`): thread-safe via `_sheet_update_lock`; 3-attempt retry with exponential back-off; forced sheet reconnection on failure; validates column existence against live sheet headers before writing.
- **Credits sheet** (`_update_credits_completion()`): thread-safe; input validation for email, total, used; 3-attempt retry with forced reconnect.
- **Drive upload** (`upload_to_drive()`): 3-attempt retry with exponential back-off; 5 GB file-size guard; graceful shutdown check inside chunked upload loop.
- **Browser close** (`close_browser()`): copies context/page lists before iteration to avoid modification-during-iteration race; guards `_browser.is_connected()` before calling `.close()`.
- **FFmpeg** (`build_ffmpeg_cmd()`): validated trim vs. duration edge case (trim ≥ duration → use full video); minimum crossfade floor (0.1 s) and 25 % cap of main video duration; raises `ValueError` instead of producing a broken command.
- **`run_ffmpeg()`**: uses context-manager `Popen` for guaranteed resource release; logs last 5 lines of FFmpeg output on non-zero exit code; handles `TimeoutExpired` explicitly.
- **`process_video()`**: validates output file existence and integrity after FFmpeg finishes; removes corrupt partial files on failure; 100 KB minimum size check on input.
- **Step 3** (`step3()`): "Animate All" button detection and per-scene animation progress loop; safe popup dismissal that avoids closing important stage windows.
- **Step 4** (`step4()`): render poll loop guards `page.is_closed()`; page-reload recovery on evaluation errors; explicit shutdown check inside chunked Drive upload.
- `_get_oauth_credentials()`: catches token refresh errors and falls back to a fresh OAuth flow instead of crashing.
- README version badge updated from `v1.0.0` → `v2.0.3`.

### Fixed
- `_credits_used` global not reset between loop cycles in `run_cli_mode()` — now reset at the top of each `while True` cycle.

### Notes
- Stable release candidate. All three pipeline modes (`combined`, `generate`, `process`) and the interactive menu fully exercised.
- `Process_D_Link` column referenced in processing logic but not defined in `SHEET_SCHEMA` — handled gracefully via `_actual_sheet_cols()` fallback.
- Bare `except:` clauses in Playwright interaction helpers (popup/modal dismissal) are intentional — any DOM error must be silently suppressed to keep automation running.
