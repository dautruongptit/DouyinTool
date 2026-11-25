@echo off
chcp 65001 >nul
title Nimo Kids Tool - khoi dong (phien ban: xem docs/CHANGELOG.md)
cd /d "%~dp0"

rem ---- 1. Tim Python ----
rem Uu tien Python 3.13 -> 3.10 (Python 3.14/3.15 qua moi, faster-whisper chua ho tro)
set "PY="
for %%v in (3.13 3.12 3.11 3.10) do (
  if not defined PY py -%%v -c "import sys" >nul 2>nul && set "PY=py -%%v"
)
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY (
  echo Chua cai Python. Hay cai tu python.org ^(tick "Add python.exe to PATH"^), roi bam lai file nay.
  start "" https://www.python.org/downloads/
  pause
  exit /b
)

rem ---- 2. Cai thu vien (chi lan dau) ----
%PY% -c "import playwright, requests, PIL, tkinter" >nul 2>nul
if errorlevel 1 (
  echo Lan dau chay: dang cai thu vien, doi 1-2 phut...
  %PY% -m pip install --user --upgrade playwright requests pillow
  %PY% -c "import playwright, requests, PIL, tkinter" >nul 2>nul
  if errorlevel 1 (
    echo.
    echo Cai thu vien KHONG thanh cong. Chup man hinh cua so nay gui lai nhe.
    pause
    exit /b
  )
)

rem ---- 3. Tim pythonw (chay khong hien cua so lenh) ----
set "PYW="
for /f "delims=" %%i in ('%PY% -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "PYW=%%i"
if not exist "%PYW%" for /f "delims=" %%i in ('%PY% -c "import sys;print(sys.executable)"') do set "PYW=%%i"

rem ---- 4. Tao icon ngoai Desktop (chi lan dau) ----
set "NK_TARGET=%PYW%"
set "NK_SCRIPT=%~dp0nimokids_tool.py"
set "NK_DIR=%~dp0"
set "NK_ICON=%~dp0nimokids.ico"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $l=Join-Path $d 'Nimo Kids Tool.lnk'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($l); $s.TargetPath=$env:NK_TARGET; $s.Arguments=[char]34+$env:NK_SCRIPT+[char]34; $s.WorkingDirectory=$env:NK_DIR; $s.IconLocation=$env:NK_ICON; $s.Description='Nimo Kids Tool'; $s.Save()" >nul 2>nul

where ffmpeg >nul 2>nul || echo Luu y: chua co ffmpeg ^(tab Ghep video va Anh bia can^). Cai bang lenh: winget install Gyan.FFmpeg

rem ---- 5. Mo tool ----
start "" "%PYW%" "%~dp0nimokids_tool.py"
exit /b
