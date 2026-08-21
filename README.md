# Audiobook Forge

A PySide6 desktop app for authoring a chapterized M4B audiobook from MP3, M4A, AAC, FLAC, WAV, or OGG files.

## Run

1. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Make sure `ffmpeg` is available. The app checks a bundled executable beside the app, a configured executable, system `PATH`, and `%USERPROFILE%\.spotdl\ffmpeg.exe`. Configure FFmpeg and FFprobe from the **Tools** menu when needed.

3. Start the GUI:

   ```powershell
   python main.pyw
   ```

Drop audio files or a complete audiobook folder into the chapter list. Use the sort control, drag rows for manual order, double-click chapter titles to edit them, enter book metadata, choose quality/channel settings, and export. Projects can be saved as JSON from the **Project** menu.
