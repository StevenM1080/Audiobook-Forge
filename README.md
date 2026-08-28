# Audiobook Forge

A PySide6 desktop app for authoring a chapterized M4B audiobook from MP3, M4A, AAC, FLAC, WAV, or OGG files.

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

Drop audiobook folders or groups of audio files into the book tree. Each folder is one book, and files selected in one action form one book. Expand or collapse books, drag chapters within a book for manual order, double-click chapter titles to edit them, select books to edit their metadata, choose per-book quality/channel settings, choose one batch destination folder, and export all books. Projects can be saved as JSON from the **Project** menu.

When importing a book folder, Audiobook Forge automatically looks for `Cover.jpg`, `Cover.jpeg`, `Cover.png`, or `Cover.webp`, as well as images inside a `Cover` subfolder. If none is present, the cover field simply remains empty and can be filled manually.

Batch output is organized as `Destination\Author\[Series]\[Series Number - ]Title\Title.m4b`. Existing author and series folders are reused. Books are exported sequentially and committed after validation; cancelling or failing a later book preserves all earlier completed books and stops the remaining queue.

Each source chapter is normalized to a compatible temporary audio stream before the final M4B is assembled. The completed audiobook is validated in a staging directory and only then replaces the selected destination, so cancellation or conversion failure does not delete an existing audiobook.

Project files reference the original audio and cover files by absolute path; they do not embed source media. Keep those files available or re-add moved tracks before exporting. New projects use the version 2 multi-book format; version 1 single-book projects are migrated when opened.

## Test

Install the development requirements and run the suite:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

When FFmpeg is available, the suite includes a short generated MP3/WAV-to-M4B export with cover and metadata verification.
