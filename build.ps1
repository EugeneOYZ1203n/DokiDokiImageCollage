# Build dist\DokiDokiCollage\DokiDokiCollage.exe in a clean venv (avoids stray opencv variants).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path .build-venv) { Remove-Item -Recurse -Force .build-venv }
python -m venv .build-venv
& .\.build-venv\Scripts\python.exe -m pip install --upgrade pip
& .\.build-venv\Scripts\python.exe -m pip install -e ".[build]"
& .\.build-venv\Scripts\python.exe -m PyInstaller collage.spec --noconfirm --clean
Write-Host "Built: dist\DokiDokiCollage\DokiDokiCollage.exe"
