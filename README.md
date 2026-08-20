# Audiobook Forge

A small PySide6 desktop app that combines ordered MP3 files into one chapterized M4B audiobook.

## Run

1. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Make sure `ffmpeg` is available. The app also recognizes `%USERPROFILE%\.spotdl\ffmpeg.exe`; MP3 durations are read with Mutagen, so `ffprobe` is not required.

3. Start the GUI:

   ```powershell
   python main.pyw
   ```

Drop MP3s into the chapter list, drag rows to reorder them, enter the title and author, optionally add cover art, then choose an output path and export.
