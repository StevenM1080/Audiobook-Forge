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

Drop audio files or a complete audiobook folder into the chapter list. Use the sort control, drag rows for manual order, double-click chapter titles to edit them, enter book metadata, choose quality/channel settings, and export. Projects can be saved as JSON from the **Project** menu.

Each source chapter is normalized to a compatible temporary audio stream before the final M4B is assembled. The completed audiobook is validated in a staging directory and only then replaces the selected destination, so cancellation or conversion failure does not delete an existing audiobook.

Project files reference the original audio and cover files by absolute path; they do not embed source media. Keep those files available or re-add moved tracks before exporting.

## Test

Install the development requirements and run the suite:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

When FFmpeg is available, the suite includes a short generated MP3/WAV-to-M4B export with cover and metadata verification.
