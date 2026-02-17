param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

if ($Clean) {
    Write-Host "Cleaning old build artifacts..."
    Remove-Item -Recurse -Force .\build -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue
}

Write-Host "Installing runtime dependencies..."
python -m pip install -r requirements.txt

Write-Host "Installing packager..."
python -m pip install pyinstaller

Write-Host "Building music-picker.exe ..."
python -m PyInstaller --noconfirm --clean --onefile --windowed --name music-picker main.py

Write-Host "Build completed. Output: .\\dist\\music-picker.exe"
