@echo off
cd /d "%~dp0"
echo Search the latest downloaded job feed.
echo Examples: mechanical, test, manufacturing, RTX
python -m src.search --interactive
pause
