@echo off
cd /d "%~dp0"
echo Refreshing employer postings. Large employers can take several minutes.
python -m src.puller
pause
