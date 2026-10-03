@echo off
rem Lanceur cliptv pour Windows : double-clic. Installe ce qui manque puis ouvre l'app.
setlocal EnableExtensions
title cliptv
cd /d "%~dp0"
echo.
echo   === cliptv ===
echo.

rem ---------- Python 3.10 ou plus ----------
call :find_python
if not defined PY (
  echo Python introuvable : installation automatique avec winget...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  call :refresh_path
  call :find_python
)
if not defined PY (
  echo.
  echo [ERREUR] Python n'a pas pu etre installe automatiquement.
  echo Installe Python 3.12 depuis https://www.python.org/downloads/
  echo en cochant "Add python.exe to PATH", puis relance ce fichier.
  goto :fail
)

rem ---------- ffmpeg ----------
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo ffmpeg introuvable : installation automatique avec winget...
  winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
  call :refresh_path
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERREUR] ffmpeg n'a pas pu etre installe automatiquement.
  echo Ferme cette fenetre et relance ce fichier. Si ca ne suffit pas, installe ffmpeg
  echo depuis https://www.gyan.dev/ffmpeg/builds/ et ajoute son dossier bin au PATH.
  goto :fail
)

rem ---------- environnement Python de l'app ----------
if not exist ".venv\Scripts\python.exe" (
  echo Creation de l'environnement Python...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)
echo Installation / mise a jour des dependances (la premiere fois : quelques minutes)...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -e ".[all]"
if errorlevel 1 goto :fail

rem Windows peut demander d'autoriser l'acces reseau : accepte pour ouvrir l'app
rem depuis tes autres appareils (sinon elle reste accessible sur ce PC seulement).
".venv\Scripts\python.exe" -m clipbot app --host 0.0.0.0 --open
pause
exit /b 0

:find_python
set "PY="
for %%C in ("py -3.13" "py -3.12" "py -3.14" "py -3.11" "py -3.10" "py -3" "python") do (
  if not defined PY (
    %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=%%~C"
  )
)
exit /b 0

:refresh_path
for /f "usebackq tokens=*" %%P in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%P"
exit /b 0

:fail
echo.
echo Une erreur est survenue (voir ci-dessus).
pause
exit /b 1
