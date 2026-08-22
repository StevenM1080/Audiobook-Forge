# Audiobook Forge: Codex Handoff

## Purpose

Audiobook Forge is a Windows PySide6 desktop application intended to convert a set of ordered audio tracks into one chapterized M4B audiobook.

The original workflow is:

1. Add MP3 files.
2. Arrange them in chapter order.
3. Enter title and author.
4. Optionally add cover art.
5. Choose an output path.
6. Make an M4B.

The user wants Codex to refine the application into a robust, polished audiobook-authoring tool while preserving that workflow.

## Repository State

- Repository: `StevenM1080/Audiobook-Forge`
- Local path: `D:\VS Code\MP3 to M4b`
- Branch: `main`
- Remote: `https://github.com/StevenM1080/Audiobook-Forge.git`
- Current commit: `c1457e5 Fix metadata escaping test`
- Local branch and `origin/main` were synchronized to that commit.
- Working tree was clean after the rollback.
- Primary entry point: `main.pyw`
- Python target: Windows, currently developed with Python 3.11 in `.venv`; a Python 3.14 interpreter was also detected in VS Code.

The user explicitly requested a rollback to commit `c1457e5`. Do not restore later commits automatically without confirming with the user.

## Important Current-State Inconsistency

At `c1457e5`, `main.pyw` is the older implementation. It imports `mutagen.mp3.MP3`, accepts only `.mp3`, and does not use the newer helper modules.

The repository still contains helper modules and tests from the later experimental upgrade:

- `audiobook_forge/models.py`
- `audiobook_forge/media.py`
- `audiobook_forge/cover.py`
- `audiobook_forge/project_io.py`
- `tests/test_core.py`
- `tests/test_project_io.py`

The current `README.md` describes features from the later upgrade that are not all present in the active `main.pyw`. Codex should first choose and document a coherent baseline, then reconcile or remove stale pieces carefully. Do not assume the README is proof that a feature is active.

## Active Older Application Behavior

The active older `main.pyw` currently contains:

- Dark Fusion/PySide6 GUI.
- Two-column layout.
- `QListWidget` chapter list.
- MP3 file drag/drop and file browsing.
- Manual row movement through `QListWidget.InternalMove`.
- Title and author line edits.
- Cover drag/drop and browse field with preview.
- Output file browse field.
- A threaded `ConversionWorker` using `QThread`.
- Mutagen MP3 duration probing.
- Temporary concat and FFmetadata files.
- FFmpeg AAC encoding at hard-coded 96 kbps.
- Chapter titles derived from source filenames.
- FFmpeg progress displayed as processed audio time.
- Basic failure dialog.

Known weaknesses in this active version include:

- Only `.mp3` is supported.
- No folder import.
- No natural sorting.
- The list is the effective state store; chapter titles are not modeled separately.
- No Remove Selected action.
- Row numbering can become stale after manual reorder.
- No expanded metadata beyond title and author.
- No robust FFmpeg/FFprobe discovery configuration.
- No cancellation in the older baseline.
- No project save/load in the active entry point.
- No output validation in the active entry point.
- Cover art is embedded as selected, without guaranteed normalization.
- The worker has minimal diagnostics and hard-coded encoding settings.
- The active code may not match the later README wording.

## Helper Modules Present

### `audiobook_forge/models.py`

Contains:

- `SUPPORTED_AUDIO_EXTENSIONS`: `.mp3`, `.m4a`, `.aac`, `.flac`, `.wav`, `.ogg`.
- `Chapter` dataclass with `path`, `title`, `duration`, and optional `track_number`.
- `BookMetadata` dataclass with title, author, narrator, series, series number, year, and genre.
- `natural_sort_key()` for numeric filename ordering.
- `estimate_output_bytes()`.

### `audiobook_forge/media.py`

Contains:

- Generalized Mutagen `File(..., easy=True)` probing.
- `probe_audio()` returning a `Chapter`.
- File-specific unreadable-media errors.
- `supported_audio_files()` for non-recursive folder discovery.
- `common_tags()` for consistent embedded tag candidates.

### `audiobook_forge/cover.py`

Contains a cover normalizer using Qt image APIs:

- Reads JPG, JPEG, PNG, or WebP.
- Scales down to a maximum size.
- Places artwork on a square black canvas.
- Writes a temporary JPEG.
- Does not modify the source image.

### `audiobook_forge/project_io.py`

Contains versioned JSON save/load helpers for chapters, metadata, cover path, output path, bitrate, and channel mode.

The project format stores source paths and does not embed source audio.

## Previous Implementation Phases

These commits were created during the earlier implementation attempt. The branch was later intentionally reset to `c1457e5`, so the commits after it are not active branch tips. They remain in the repository's reachable history as ancestors/descendants depending on Git history, but should be treated as historical context only.

- `43d00f6 Add initial project files: .gitignore, README, main.pyw, and requirements.txt`
  - Created the initial PySide6 app, README, requirements, and ignore file.
- `96c236c Add chapter and media foundation`
  - Added chapter/book models, generalized media helpers, natural sorting, estimates, and initial tests.
- `c309cb9 Integrate chapter model and folder import`
  - Experimented with explicit chapter state, multiple audio formats, folder import, title editing, removal, sorting, durations, and estimates.
- `923b739 Add safe export cancellation and diagnostics`
  - Experimented with cancellation, output cleanup, overwrite protection, progress output, and retained FFmpeg diagnostics.
- `8f64d3d Add audiobook metadata and encoding presets`
  - Experimented with narrator/series/year/genre fields, bitrate presets, channel handling, and configurable FFmpeg discovery.
- `106c912 Add project persistence and output validation`
  - Experimented with QSettings, JSON projects, cover normalization, metadata autofill, and FFprobe chapter validation.
- `daacac6 Add sorting and export safeguards`
  - Experimented with manual/natural/track sorting, disk-space warnings, and explicit FFprobe selection.
- `ba99e72 Prevent book details layout clipping`
  - Added a scrollable details pane to address vertical clipping.
- `8df3010 Stabilize startup window and cover layout`
  - Attempted to stabilize opening dimensions and cover expansion.
- `d62f588 Fix details form vertical sizing`
  - Added explicit details-form sizing.
- `7dbd8e6 Match fixed compact window layout`
  - Removed scrolling, fixed the window to `760 x 700`, compacted the form, and made the cover area expand locally.
- `c1457e5 Fix metadata escaping test`
  - Corrected the metadata escaping test. This is the requested rollback target and current branch tip.

## User Interface Feedback History

The user provided screenshots and feedback that should guide future refinement:

1. The initial GUI looked reasonable but export startup appeared to crash.
2. Long exports displayed values such as `504:11`; this was clarified as processed audio timestamp, not wall-clock time.
3. Progress wording was changed to the clearer format:
   - `Processed audio: 08:24:11 / 11:47:12`
4. The details form repeatedly became clipped or overlapped when the window was resized.
5. The user did not want scrolling and did not want the form squished.
6. The desired layout was a compact fixed composition matching the provided screenshot.
7. The later layout experiment used a fixed `760 x 700` window, no scroll area, compact vertical spacing, and a cover area that expanded locally from approximately 150 px to 190 px.
8. That later layout was subsequently rolled back when the user requested `c1457e5`.

Codex should use actual rendered screenshots and geometry checks when refining the UI. Avoid relying only on `sizeHint()` for nested layouts.

## Dependencies

`requirements.txt` currently contains:

```text
PySide6>=6.6
mutagen>=1.47
```

The development environment used during prior validation had:

- PySide6 installed.
- Mutagen installed.
- FFmpeg available at `%USERPROFILE%\.spotdl\ffmpeg.exe` on the development machine.
- No sibling `ffprobe.exe` was available there.
- A project `.venv` with pytest installed was eventually available.

The application should not assume the developer's `.spotdl` location in a packaged build.

## Validation Commands

From the repository root in PowerShell:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Compile all Python files without relying on PowerShell wildcard expansion:

```powershell
$files = @('main.pyw') + (Get-ChildItem audiobook_forge -Filter '*.py').FullName + (Get-ChildItem tests -Filter '*.py').FullName
.venv\Scripts\python.exe -m py_compile $files
```

Run the GUI headlessly for smoke checks:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python.exe main.pyw
```

The Qt environment may print a non-fatal font-directory warning from PySide6 in headless mode.

The last known test result before rollback was:

```text
4 passed in 0.10s
```

Those tests cover natural sorting, metadata escaping, output estimation, and project JSON round-tripping. They do not cover full GUI behavior or a complete encode.

## Recommended Codex Work Plan

### 1. Establish a coherent baseline

- Inspect `git show c1457e5:main.pyw` and all current working files.
- Decide whether to integrate the helper modules into `main.pyw` or remove stale helpers.
- Update README only after behavior is actually implemented.
- Preserve source audio and cover files.

### 2. Separate application layers

Prefer a maintainable structure such as:

```text
audiobook_forge/
    models.py
    media.py
    cover.py
    project_io.py
    services/
    ui/
main.pyw
```

Keep expensive probing, image processing, FFmpeg encoding, FFprobe validation, and project I/O outside the GUI thread.

### 3. Build a real chapter model

Use a list of `Chapter` objects as authoritative state. Each chapter should include:

- Source path.
- Editable title.
- Measured duration.
- Optional embedded track number.

Use a model/view widget or carefully synchronize a custom list view. Do not use display text as the data source because numbering and duration formatting make parsing fragile.

### 4. Implement import and ordering

- Accept individual supported audio files.
- Accept a non-recursive folder drop and Add Folder.
- Natural-sort folder contents by default.
- Support embedded track-number sorting.
- Preserve manual order after a drag.
- Renumber display rows after every mutation.

### 5. Make the fixed UI deliberate

The user prefers no scrolling and no squished content. Choose a defined fixed/default size based on a rendered reference screenshot. Use compact but readable controls, explicit minimum/maximum sizes, and geometry tests or screenshots. If all metadata cannot fit at the chosen dimensions, simplify the presentation rather than allowing overlap.

### 6. Improve conversion reliability

- Discover bundled FFmpeg/FFprobe beside the executable first.
- Offer configured paths and remember them.
- Use argument lists, never shell command strings.
- Normalize cover art into a temporary JPEG.
- Use accurate cumulative chapter timestamps.
- Add bitrate presets: 64, 96, 128, 160 kbps.
- Add preserve/mono/stereo channel modes.
- Add safe cancellation that terminates FFmpeg, waits, cleans partial output, and restores controls.
- Keep relevant FFmpeg diagnostics.
- Do not silently overwrite an existing output.
- Validate output existence, duration, and chapter count when FFprobe is available.

### 7. Metadata and projects

- Prefill empty fields only from consistent embedded tags.
- Support title, author, narrator, series, series number, year, and genre.
- Save/load JSON projects with relative or absolute path strategy clearly documented.
- Handle missing/moved source files visibly and gracefully.
- Persist appropriate preferences with QSettings.

### 8. Tests

At minimum add tests for:

- Natural filename sorting.
- Embedded track sorting.
- Metadata escaping including `=`, `;`, `#`, backslashes, newlines, and Unicode.
- Chapter boundary continuity.
- Output size estimates.
- Project save/load.
- FFmpeg command construction for bitrate/channel/cover combinations.
- Missing/unreadable source diagnostics.

Avoid requiring a long real audiobook encode in every test. Use short generated fixtures for one end-to-end test.

## Safety Constraints

- Never delete or rewrite source audio files.
- Never modify the original cover image.
- Do not use destructive Git commands unless explicitly requested.
- Do not force-push unless the user explicitly asks to rewrite the remote branch history.
- Check current file contents before editing because the user has previously undone implementation edits.
- Commit major changes with clear messages if requested by the user.
- Run focused validation immediately after each substantive edit.

## Suggested First Codex Prompt

> Inspect the current repository at commit `c1457e5`. Reconcile the active older `main.pyw` with the stale helper modules and README. Preserve the original MP3-to-chapterized-M4B workflow, then implement Phase 1 only: explicit chapter model, generalized probing, folder/file import, natural sorting, editable titles, remove selected, correct renumbering, and duration display. Keep the UI fixed and non-scrolling at the user-approved screenshot dimensions. Add focused tests, run them, and report any unresolved UI geometry issues before proceeding.
