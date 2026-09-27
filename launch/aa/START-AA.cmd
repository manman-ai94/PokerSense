@echo off
setlocal
set "AA_ROOT=%~dp0..\.."
if exist "%~dp0PokerSense-AA.exe" (
  "%~dp0PokerSense-AA.exe" %*
) else if exist "%AA_ROOT%\dist\PokerSense-AA\PokerSense-AA.exe" (
  "%AA_ROOT%\dist\PokerSense-AA\PokerSense-AA.exe" %*
) else if exist "%AA_ROOT%\.venv\Scripts\python.exe" (
  "%AA_ROOT%\.venv\Scripts\python.exe" "%AA_ROOT%\packaging\aa_live_entry.py" %*
) else (
  py -3.11 "%AA_ROOT%\packaging\aa_live_entry.py" %*
)
if errorlevel 1 pause
endlocal
