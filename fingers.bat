@echo off
rem Full 7-piece kit, AR view, bare fingers as sticks. Extra arguments are passed through (e.g. --no-audio).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m spacedrums.app.play --view ar --demo --kit full --fingers %*
