# MediaPorter (Windows Desktop App)

MediaPorter is a Windows-friendly GUI app for downloading Bilibili audio/video, with built-in QR login and per-task file naming.

## Highlights

- Batch download from Bilibili URLs (`video`, `bangumi/ep/ss`, `movie`, `b23.tv`)
- Audio mode and video mode
- Video quality selection (`Auto / 1080p / 720p / 480p`)
- Per-task custom filename (one task per line)
- Built-in Bilibili QR login (auto-generate cookie file)
- Login/VIP check before downloading paid/VIP content
- Retry failed tasks
- Download history and detailed logs
- FFmpeg environment detection + one-click installer (opens visible terminal)

## Requirements

- Windows
- Python 3.10+
- Internet access

## Installation

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Input Format (Important)

MediaPorter supports **one task per line**:

```text
<url>
<url> || <custom file name>
```

Examples:

```text
https://www.bilibili.com/video/BVxxxx
https://www.bilibili.com/bangumi/play/epxxxx || Episode_01
https://b23.tv/xxxx || My_Custom_Name
```

## How To Use

### 1) Basic Download

1. Paste tasks in the input box (or load into the task editor table).
2. Select output folder.
3. Choose mode:
   - `Audio` for music/audio extraction
   - `Video` for full video
4. (Video mode) choose quality.
5. Click `Start Download`.

### 2) Download VIP / Paid Content

Recommended flow:

1. Click `QR Login Bilibili`.
2. Use Bilibili mobile app to scan and confirm.
3. App auto-switches to cookie-file mode after login.
4. Click `Check Login/VIP` to verify account status.
5. Start download.

### 3) Custom File Name Per URL

- Use `url || filename` in input text, or edit filename in task table.
- App auto-sanitizes invalid Windows filename characters.

### 4) FFmpeg (For Best Video Compatibility)

- In `Environment`, if FFmpeg is missing, click `Install FFmpeg (Auto)`.
- A **visible terminal window** opens and runs `winget`.
- Follow terminal output and close window after completion.

## QR Login Behavior

- QR has countdown and auto-refresh.
- On successful login, cookie file is saved under `.auth/`.
- Login/VIP report is shown in the message panel.

## Packaging (Windows EXE)

### One-command script

```powershell
.\build_windows.ps1 -Clean
```

Output:

- `dist/MediaPorter.exe`

### Manual

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name MediaPorter main.py
```

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## GitHub Release Workflow

Workflow file: `.github/workflows/release-windows.yml`

- Trigger: push tag like `v0.2.0`
- Build artifact:
  - `MediaPorter.exe`
  - `MediaPorter.exe.sha256`

## Troubleshooting

- `Login may be required`:
  - Run `Check Login/VIP` first.
  - Re-login with QR flow.
- `Browser cookies could not be decrypted/read (DPAPI)`:
  - Use built-in QR login (recommended).
- Video has no audio / video fails:
  - Ensure FFmpeg is installed.
- Install terminal not opening:
  - Run app as normal desktop user and retry.

---

Version: **v0.2.0**
