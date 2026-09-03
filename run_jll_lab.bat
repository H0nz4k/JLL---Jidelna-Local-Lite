@echo off
setlocal
bash.exe "%~dp0tools\run_jll_lab.sh"
if errorlevel 9009 (
  echo Git Bash nebyl nalezen v PATH.
  echo Spustte tools\run_jll_lab.sh z Git Bash.
  exit /b 2
)
exit /b %ERRORLEVEL%
