@echo off
setlocal
for %%I in ("%~dp0..\..") do set "AA_ROOT=%%~fI"
if exist "%AA_ROOT%\packaging\aa_live_entry.py" goto source
if exist "%~dp0PokerSense-AA.exe" goto adjacent_exe
if exist "%AA_ROOT%\dist\PokerSense-AA\PokerSense-AA.exe" goto dist_exe
echo [AA] ERROR: AA source entry and packaged executable are missing.
set "AA_EXIT=2"
goto done

:source
echo [AA] Source checkout: "%AA_ROOT%"
if not exist "%~dp0source_launcher.py" (
  echo [AA] ERROR: source_launcher.py is missing from this checkout.
  set "AA_EXIT=2"
  goto done
)
if exist "%AA_ROOT%\.venv\Scripts\python.exe" goto venv
where py.exe >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0source_launcher.py" %*
  goto finish
)
where python.exe >nul 2>&1
if not errorlevel 1 (
  python "%~dp0source_launcher.py" %*
  goto finish
)
echo [AA] ERROR: Python 3.11-3.13 was not found. Install Python or create this checkout's .venv.
set "AA_EXIT=3"
goto done

:venv
"%AA_ROOT%\.venv\Scripts\python.exe" "%~dp0source_launcher.py" %*
goto finish

:adjacent_exe
echo [AA] Packaged entry: "%~dp0PokerSense-AA.exe"
"%~dp0PokerSense-AA.exe" %*
goto finish

:dist_exe
echo [AA] Packaged entry: "%AA_ROOT%\dist\PokerSense-AA\PokerSense-AA.exe"
"%AA_ROOT%\dist\PokerSense-AA\PokerSense-AA.exe" %*

:finish
set "AA_EXIT=%ERRORLEVEL%"
:done
if not "%AA_EXIT%"=="0" (
  echo [AA] Launcher failed with exit code %AA_EXIT%.
  if "%~1"=="" pause
)
endlocal & exit /b %AA_EXIT%
