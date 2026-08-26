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
- Baseline commit before the current repair work: `3d4db0e Add Codex implementation handoff`.
- The `main.pyw` content at that baseline is identical to `c1457e5` and already uses the helper modules.
- Check `git status` before editing because the working tree may contain active repair work.
- Primary entry point: `main.pyw`
- Python target: Windows. The current `.venv` uses Python 3.14.

The user rejected the later small, squished layout experiment. Do not restore those layout changes automatically.

## Current Application Baseline

The active `main.pyw` uses the `audiobook_forge` helper modules and supports the broader authoring workflow described by the README. The previous claim that `c1457e5` contained an MP3-only entry point was incorrect.

The active modules are:

- `audiobook_forge/models.py`
- `audiobook_forge/media.py`
- `audiobook_forge/cover.py`
- `audiobook_forge/exporter.py`
- `audiobook_forge/project_io.py`
- `tests/test_core.py`
- `tests/test_exporter.py`
- `tests/test_project_io.py`
- `tests/test_ui.py`

The application currently contains:

- Dark Fusion/PySide6 GUI.
- Roomy, resizable two-column layout.
- Explicit `Chapter` model synchronized with the chapter list.
- File and non-recursive folder import for MP3, M4A, AAC, FLAC, WAV, and OGG.
- Natural, embedded-track, and manual ordering.
- Editable chapter titles, removal, duration display, and output estimates.
- Extended book metadata.
- Cover drag/drop and browse field with preview.
- A threaded `ConversionWorker` using `QThread`.
- Mixed-format normalization before final assembly.
- Temporary staged output followed by validated atomic replacement.
- Cover normalization and FFmpeg/FFprobe discovery.
- Encoding presets, channel handling, cancellation, and diagnostics.
- Versioned JSON project save/load.
- FFmpeg progress displayed as processed audio time.

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
- Several later layout commits experimented with scrolling and compressed geometry.
  - Those experiments produced the rejected small, squished result and should not be reapplied.
- `c1457e5 Fix metadata escaping test`
  - Corrected the metadata escaping test and retained the roomier application layout.

## User Interface Feedback History

The user provided screenshots and feedback that should guide future refinement:

1. The initial GUI looked reasonable but export startup appeared to crash.
2. Long exports displayed values such as `504:11`; this was clarified as processed audio timestamp, not wall-clock time.
3. Progress wording was changed to the clearer format:
   - `Processed audio: 08:24:11 / 11:47:12`
4. The desired reference is the first user-provided screenshot: a roomy, readable, resizable two-column window.
5. The second screenshot is explicitly rejected because the details form and cover controls are compressed and overlap.
6. There is no required fixed pixel size. Preserve proportions and prevent controls from overlapping as the window is resized.

Codex should use actual rendered screenshots and geometry checks when refining the UI. Avoid relying only on `sizeHint()` for nested layouts, and do not introduce a fixed compact window size.

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

The current repair suite result is:

```text
37 passed
```

The suite includes a short generated mixed-format end-to-end encode as well as focused exporter, project, ordering, drag/drop, cover-state, metadata, and model tests.

## Current Repair Status

Implemented in the current working tree:

- Normalize every source chapter to a consistent AAC stream before concatenation.
- Assemble and validate the M4B in a temporary directory on the destination volume.
- Atomically replace the requested destination only after successful validation.
- Preserve an existing destination after preflight, encoding, validation, or cancellation failure.
- Validate duration, chapter count/boundaries/titles, audio presence, and cover art using FFprobe when available and Mutagen as the local fallback; the end-to-end test also verifies core metadata tags.
- Discover bundled, configured, PATH, sibling, and `.spotdl` FFmpeg/FFprobe tools.
- Fix cover drag/drop state, internal chapter drag acceptance, full-list sorting, manual-order preservation, source snapshots during export, and export-time control locking.
- Validate projects, save them atomically, resolve legacy relative paths, report missing sources, and clear stale cover previews.
- Remove the hard-coded undersized window minimum and rely on content-derived minimum geometry.
- Do not restore or save window geometry; only bitrate and channel preferences persist so a previously squished session cannot dictate the next layout.
- Keep the output placeholder readable and initialize the splitter with a roomy chapter/details balance so the details controls do not collapse into a narrow column.

Useful remaining refinements:

- Move large-folder probing and metadata reads off the GUI thread.
- Replace decorated `QListWidget` editing with a dedicated model/delegate.
- Add unsaved-project tracking, moved-file relinking, and recent projects.
- Add an in-app tool/version status report, packaging, and Windows CI.

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

### 5. Preserve the roomy, resizable UI

Use the first user-provided screenshot as the visual reference. Keep the two-column composition spacious and resizable, prevent overlap at the minimum usable dimensions, and do not impose the rejected compact fixed-size layout.

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

## Suggested Continuation Prompt

> Continue refining the current Audiobook Forge working tree. Preserve the roomy, resizable two-column layout shown in the preferred screenshot. Run the focused tests and short generated-media export test after changes, and never modify source audio or replace an existing destination until a staged export has passed validation.
