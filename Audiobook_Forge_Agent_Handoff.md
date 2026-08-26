# Audiobook Forge --- VS Code Agent Implementation Handoff

## Objective

Upgrade the existing **Freedom / Audiobook Forge** PySide6 application
into a robust, polished Windows audiobook-authoring tool.

The existing `main.pyw` already provides MP3 drag/drop, manual chapter
reordering, title/author fields, cover art, M4B output, FFmpeg
conversion, Mutagen duration probing, threaded conversion, progress
reporting, and a dark PySide6 UI.

Preserve existing working behavior unless this specification explicitly
replaces it.

## 1. Expand Supported Audio Formats

Currently only `.mp3` is accepted. Add:

-   `.mp3`
-   `.m4a`
-   `.aac`
-   `.flac`
-   `.wav`
-   `.ogg`

Use generalized Mutagen probing (`mutagen.File`) and/or FFprobe rather
than assuming `mutagen.mp3.MP3`. Unreadable files must identify the
offending file instead of crashing the application.

## 2. Folder Import and Folder Drag/Drop

Allow a complete audiobook folder to be dropped onto the chapter list.
Also add an **Add Folder** button.

On folder import:

1.  Find supported audio files in that folder.
2.  Import them.
3.  Natural-sort by filename.

Example ordering must be:

``` text
Chapter 1
Chapter 2
Chapter 3
Chapter 10
```

not `1, 10, 2, 3`.

Do not recursively consume arbitrary nested folders unless explicitly
exposed as an option.

## 3. Chapter Sorting

Support:

-   Natural filename
-   Embedded track number
-   Manual order

Natural filename sorting is the default for folder import. Once the user
manually arranges chapters, never silently reorder them.

## 4. Fix Numbering After Reorder

Visible chapter numbers currently reflect insertion order even after
rows are dragged.

After add, remove, sort, or manual reorder, renumber rows sequentially:

``` text
01
02
03
...
```

The displayed order must always match M4B chapter order.

## 5. Editable Chapter Titles

Maintain chapter state separately from source filenames. Each chapter
should contain at least:

-   source path
-   chapter title
-   duration
-   source track number if available

Allow chapter titles to be edited without renaming source files.
Double-click editing is acceptable.

Use the edited title in FFmetadata.

## 6. Remove Selected

Add **Remove Selected** using the list's existing extended selection
support.

After removal:

-   update the chapter model
-   renumber rows
-   recalculate total duration
-   recalculate estimated output size

Keep **Clear** as a separate action.

## 7. Duration Display

Show chapter duration in the list, for example:

``` text
01   Chapter One                         12:34
02   Chapter Two                         08:51
```

Show total audiobook runtime elsewhere in the UI. Support hour-long
formatting such as `14:22:08`.

Duration probing must not freeze the UI for large books.

## 8. Automatic Metadata Import

Inspect embedded source tags and intelligently prefill empty fields:

-   Book/album title
-   Author / album artist
-   Artist
-   Track number
-   Year/date
-   Genre
-   Embedded cover

Do not overwrite fields the user already edited.

If all tracks consistently identify the same album and album artist,
treat those as strong candidates for Title and Author.

Use embedded artwork when no cover has already been selected.

## 9. Expanded Book Metadata

Add fields for:

-   Title
-   Author
-   Narrator
-   Series
-   Series number
-   Year
-   Genre

Write useful standards-compatible MP4/M4B metadata where practical.
Never invent missing metadata.

## 10. Cover Processing

Support JPG/JPEG, PNG, and WebP input but normalize embedded cover art
for compatibility.

Recommended output:

-   JPEG
-   square canvas
-   maximum around 1200×1200 or 1600×1600
-   sensible high JPEG quality
-   preserve aspect ratio
-   do not unnecessarily enlarge tiny images

Use padding or an explicit crop option for non-square artwork. Never
modify the original cover file.

## 11. Encoding Presets

Replace hard-coded AAC 96 kbps with:

``` text
64 kbps   — Small
96 kbps   — Standard
128 kbps  — High
160 kbps  — Very High
```

Default: **96 kbps Standard**.

Keep advanced codec complexity out of the normal workflow.

## 12. Channel Handling

Add:

-   Preserve source
-   Force mono
-   Force stereo

Default to **Preserve source**.

Generate the appropriate FFmpeg flags.

## 13. FFmpeg / FFprobe Discovery

Remove reliance on `~/.spotdl/ffmpeg.exe` as a primary fallback.

Use:

1.  bundled `ffmpeg.exe` / `ffprobe.exe` beside the application
2.  user-configured path
3.  system PATH
4.  optional legacy fallback if useful

Allow browsing for binaries when discovery fails and remember the paths.

## 14. Bundled FFmpeg Support

Design packaged Windows builds to work with:

``` text
AudiobookForge.exe
ffmpeg.exe
ffprobe.exe
```

An end user of the packaged build should not need to install FFmpeg or
edit PATH.

## 15. Persistent Settings

Use `QSettings` or equivalent to remember appropriate preferences:

-   FFmpeg path
-   FFprobe path
-   last input directory
-   last output directory
-   bitrate preset
-   channel mode
-   window geometry
-   splitter position

Do not treat temporary conversion state as general settings.

## 16. Cancellation

Add **Cancel** during export.

Cancellation must:

1.  request cancellation safely
2.  terminate FFmpeg
3.  wait for shutdown
4.  remove incomplete output
5.  clean temporary files
6.  restore UI state

Do not unsafely terminate the worker thread.

## 17. Better FFmpeg Errors

Do not reduce every FFmpeg failure to
`ffmpeg could not create the M4B file`.

Capture useful output and retain roughly the last 20--50 relevant lines.

Failure UI should provide:

-   concise summary
-   relevant source/output context
-   expandable or copyable technical details

Consider writing a troubleshooting log.

## 18. Output Validation

After FFmpeg exits successfully, validate:

-   output exists
-   output size \> 0
-   FFprobe opens it
-   duration approximately matches source total
-   chapter count matches expected chapter count

Use reasonable timing tolerance.

If validation fails, distinguish that from an encoding failure.

## 19. Existing Output Protection

Do not silently overwrite existing `.m4b` files.

If output exists, offer:

-   Replace
-   Choose another output
-   Cancel

Only invoke FFmpeg overwrite behavior after approval.

## 20. Improve Chapter Timestamp Accuracy

Current code accumulates rounded milliseconds. Improve this using
accurate FFprobe duration/timing information or high-precision
cumulative time with rounding only when FFmetadata is emitted.

Maintain:

``` text
END chapter N == START chapter N+1
```

without application-created gaps or overlaps.

## 21. Output Size Estimate

Use total duration and bitrate to show an approximate final size:

``` text
Runtime: 14h 22m
Estimated output: ~620 MB
```

Update when chapters or bitrate change. Clearly label it as an estimate.

## 22. Save / Load Projects

Create a JSON-based Audiobook Forge project format containing:

-   source paths
-   chapter order
-   edited chapter titles
-   book metadata
-   cover path
-   bitrate
-   channel mode
-   output path
-   relevant conversion settings

Do not embed source audio.

Add:

-   New Project
-   Open Project
-   Save Project
-   Save Project As

Handle moved/missing source files gracefully.

## 23. Batch Conversion --- Optional/Later

Architect the code so a future batch mode can process:

``` text
Audiobooks/
    Book A/
    Book B/
    Book C/
```

into three M4Bs.

Do not compromise the primary single-book workflow to implement batch
mode early.

## 24. UI Improvements

Preserve the current dark identity and general two-column layout.

### Chapter pane

Add:

-   Add Files
-   Add Folder
-   Remove Selected
-   Clear
-   Sort control
-   Editable chapter titles
-   Per-chapter durations
-   Total duration

### Book Details

Include:

-   Title
-   Author
-   Narrator
-   Series
-   Series number
-   Year
-   Genre
-   Cover
-   Output destination

### Encoding

Include:

-   Quality preset
-   Channel handling

### Footer

Include:

-   status
-   progress
-   estimated output size
-   Make M4B
-   Cancel while active

Keep the main interface simple rather than exposing a wall of FFmpeg
settings.

## 25. Architecture Refactor

The expanded application should no longer rely on `QListWidget` as the
authoritative state store.

Refactor responsibilities where useful, for example:

``` text
audiobook_forge/
    main.py
    ui/
        main_window.py
        widgets.py
    models/
        chapter.py
        project.py
    services/
        media_probe.py
        ffmpeg.py
        metadata.py
        cover.py
        project_io.py
```

The exact layout is flexible.

Goals:

-   UI separate from conversion logic
-   centralized FFmpeg command construction
-   centralized media probing
-   explicit chapter/project state
-   independently testable non-GUI logic

A chapter model may resemble:

``` python
@dataclass
class Chapter:
    path: Path
    title: str
    duration: float
    track_number: int | None = None
```

## 26. Threading

Expensive work must not block Qt's GUI thread.

This includes:

-   probing dozens of files
-   extracting artwork
-   cover conversion
-   FFmpeg export
-   FFprobe validation

Use Qt signals/threads safely. Never directly manipulate widgets from
worker threads.

## 27. Source Safety

Never modify source audiobook files or original cover images.

Only write:

-   temporary files
-   project files
-   final M4B
-   application settings/logs

## 28. Temporary File Safety

Continue using isolated temporary directories.

Clean them after:

-   success
-   FFmpeg failure
-   validation failure
-   cancellation

Avoid leaving large intermediate files behind.

## 29. Compatibility Goal

Generated M4Bs should work well with:

-   Jellyfin
-   iPhone/iPad audiobook apps
-   VLC
-   common desktop M4B players

Prefer conventional M4B/MP4 metadata and chapters over
application-specific tricks.

## 30. Tests

Add tests for non-GUI logic.

At minimum:

### Natural sorting

Verify `1, 2, 10`, not `1, 10, 2`.

### Metadata escaping

Test:

-   `=`
-   `;`
-   `#`
-   backslashes
-   newlines
-   Unicode

### Chapter timing

Verify:

-   sequential boundaries
-   no gaps
-   no overlaps
-   expected final duration

### Project serialization

Save/reload and verify equivalent state.

### Output estimation

Verify known duration/bitrate calculations.

### FFmpeg command construction

Verify expected flags for known configurations.

Do not require a full encode for every unit test.

## 31. Error Handling

Errors must identify the actual failure.

Bad:

``` text
Conversion failed.
```

Better:

``` text
Could not read Chapter 17:
D:\Audiobooks\Book\17.mp3

The file appears damaged or uses an unsupported format.
```

Distinguish:

-   missing source
-   unreadable source
-   FFmpeg missing
-   FFprobe missing
-   invalid cover
-   output permission error
-   insufficient disk space where detectable
-   FFmpeg failure
-   validation failure
-   cancellation

## 32. Disk-Space Check

Before export, compare available space on the destination volume against
estimated output size plus a safety margin.

Warn before starting if space appears insufficient.

The estimate is not exact, so do not treat this check as infallible.

## 33. Windows Paths / Unicode

Windows is the primary target.

Correctly handle:

-   spaces
-   apostrophes
-   parentheses
-   Unicode
-   long paths where supported

Continue invoking subprocesses with argument lists, not shell command
strings.

## 34. Packaging

Prepare for a standalone Windows build using PyInstaller or similar.

A packaged application should be capable of including:

-   app executable
-   FFmpeg
-   FFprobe
-   Qt dependencies
-   Python dependencies

Packaging must not prevent normal development/run-from-source in VS
Code.

## 35. Preserve Existing Workflow

Do not unnecessarily rewrite functionality that already works.

The original workflow must remain:

1.  Add MP3s.
2.  Arrange chapters.
3.  Enter title and author.
4.  Optionally choose cover.
5.  Choose output.
6.  Make M4B.
7.  Receive a valid chapterized audiobook.

Preserve the useful concepts already present:

-   drag/drop
-   cover preview
-   manual reordering
-   FFmetadata chapter generation
-   FFmpeg progress
-   threaded export
-   pre-export validation
-   existing visual identity

## 36. Implementation Priority

### Phase 1 --- Current Workflow

1.  Fix renumbering after drag.
2.  Remove Selected.
3.  Natural sorting.
4.  Folder import/drop.
5.  Editable chapter titles.
6.  Chapter/total duration.
7.  Better FFmpeg discovery.
8.  Better FFmpeg errors.
9.  Existing-output confirmation.
10. Cancellation.

### Phase 2 --- Metadata / Encoding

11. Generalized audio formats.
12. Metadata autofill.
13. Narrator/series/year/genre.
14. Bitrate presets.
15. Channel handling.
16. Cover normalization.
17. More accurate chapter timing.
18. Output validation.
19. Size estimate.
20. Disk-space check.

### Phase 3 --- Persistence / Architecture

21. Chapter/project models and refactor.
22. Persistent settings.
23. Save/load projects.
24. Unit tests.
25. Packaging with bundled FFmpeg/FFprobe.

### Phase 4 --- Optional

26. Batch-book processing.

## 37. Acceptance Criteria

The finished application should allow a user to:

1.  Drop a folder containing dozens of audiobook tracks.
2.  Get correct natural chapter ordering.
3.  See chapter durations.
4.  Rearrange/remove tracks.
5.  Edit chapter names.
6.  Autofill useful embedded metadata.
7.  Enter/correct title, author, narrator, series, and related metadata.
8.  Select and preview cover art.
9.  Select encoding quality.
10. Select channel handling.
11. See runtime and estimated output size.
12. Export without freezing the GUI.
13. Cancel cleanly.
14. Receive useful diagnostics on failure.
15. Receive a validated chapterized M4B.
16. Save and reopen projects.
17. Run from source in VS Code.
18. Eventually package the app with FFmpeg/FFprobe included.

## 38. Instructions to the Coding Agent

Before editing:

1.  Inspect the complete existing project.
2.  Identify current dependencies and entry points.
3.  Preserve working behavior.
4.  Make incremental, testable changes rather than replacing the
    application wholesale.
5.  Run existing tests if any.
6.  Add tests for new non-GUI logic.
7.  Test with a small sample audiobook.
8.  Never delete or overwrite source audiobook files.
9.  Keep Windows as the primary platform.
10. Favor maintainability and clear failure modes over cleverness.

If a material implementation choice differs from this handoff, document
why in project documentation or code comments where appropriate.
