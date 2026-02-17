# Music Picker (Windows App)

Music Picker is a Windows-friendly desktop app for downloading audio from Bilibili video URLs.

## Features

- Desktop GUI built with PySide6
- Multi-URL input (`bilibili.com/video` and `b23.tv`)
- Batch queue with per-task status and progress
- Configurable retry count for failed downloads
- Download folder chooser
- Logs panel and final success/failure summary
- Settings persistence:
  - last download folder
  - retry count
  - window geometry
- FFmpeg auto-detection:
  - if `ffmpeg` + `ffprobe` are in `PATH`, output is converted to MP3
  - otherwise source audio format is kept

## Project structure

```text
music_picker/
  main.py
  build_windows.ps1
  bilibili_downloader.py
  music_picker_app/
    config.py
    downloader.py
    gui.py
    models.py
    url_parser.py
    worker.py
  tests/
    test_url_parser.py
```

## Setup

1. Install Python 3.10+
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. (Optional but recommended) Install FFmpeg and add it to `PATH`.

## Run

```bash
python main.py
```

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Package for Windows

### Option A: one command script

```powershell
.\build_windows.ps1 -Clean
```

### Option B: manual command

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name music-picker main.py
```

The executable is generated at `dist/music-picker.exe`.

## GitHub auto release workflow

This repository now includes `.github/workflows/release-windows.yml`.

- Trigger: push a tag like `v0.1.0`
- Runner: `windows-latest`
- Output:
  - `music-picker.exe`
  - `music-picker.exe.sha256`
- Behavior:
  - uploads build artifact to the workflow run
  - creates/updates a GitHub Release for that tag and attaches files

Quick usage:

```bash
git add .
git commit -m "chore: add release workflow"
git push origin main
git tag v0.1.0
git push origin v0.1.0
```

## Suggested next steps

- Add per-task cancel support (not only global stop)
- Add persistent download history
- Build a full installer with Inno Setup or NSIS
