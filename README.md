# Audiobook Forge

A PySide6 desktop app for recompiling a chapterized M4B audiobook from MP3, M4A, AAC, FLAC, WAV, or OGG files. No more large books having hundreds of single-chapter audio files to manage.

## Run

1. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Make sure `ffmpeg` is available. The app checks for bundled tools beside the app, configured executables, system `PATH`, and `%USERPROFILE%\.spotdl`. Configure FFmpeg and FFprobe from the **Tools** menu when needed.

3. Start the GUI:

   ```powershell
   python main.pyw
   ```

Python 3.10 or newer is required.

Drop audiobook folders or groups of audio files into the book tree. Each folder is one book, and files selected in one action form one book. Expand or collapse books, drag chapters within a book for manual order, double-click chapter titles to edit them, select books to edit their metadata, choose whether chapter titles come from embedded tags or source file names, choose per-book quality/channel settings, choose one batch destination folder, and export all books. Projects can be saved as JSON from the **Project** menu.

Channel mode offers **Auto**, **Force mono**, and **Force stereo**. Auto samples each stereo source and downmixes the book to mono when the channels are effectively identical; bitrate remains an independent quality setting. Older projects using **Preserve source** are migrated to Auto when opened.

When importing a book folder, Audiobook Forge automatically uses a supported image in that folder as the pre-loaded cover. Conventional names such as `Cover.*`, `folder.*`, or `front.*` are preferred when multiple images are present; images inside a `Cover` subfolder are also supported. If none is present, the cover field simply remains empty and can be filled manually.

Batch output is organized as `Destination\Author\[Series]\[Series Number - ]Title\Title.m4b`. Existing author and series folders are reused. Books are exported sequentially and committed after validation; cancelling or failing a later book preserves all earlier completed books and stops the remaining queue.

Each source chapter is normalized to a compatible temporary audio stream before the final M4B is assembled. The completed audiobook is validated in a staging directory and only then replaces the selected destination, so cancellation or conversion failure does not delete an existing audiobook.

Project files reference the original audio and cover files by absolute path; they do not embed source media. Keep those files available or re-add moved tracks before exporting. New projects use the version 2 multi-book format; version 1 single-book projects are migrated when opened.

## Test

Install the development requirements and run the suite:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Build a Windows executable

Run the build script manually from PowerShell:

```powershell
.\build.ps1
```

It creates `dist\AudiobookForge.exe` and does not launch it. The script is not connected to the test suite or any automatic build hook. For exporting, place `ffmpeg.exe` and `ffprobe.exe` beside the executable, or configure them from the **Tools** menu.

When FFmpeg is available, the suite includes a short generated MP3/WAV-to-M4B export with cover and metadata verification.

## Online metadata lookup

Select a book and choose **Search metadata…** in the book-details panel to search Google Books and Open Library by title, author, or ISBN. Matching results are validated against the entered title and author before they are shown. Applying a result fills the available bibliographic fields and downloads its cover next to the source audio without replacing an existing file. Narrator and audiobook runtime are not supplied by these general book catalogs and remain available for manual entry.
