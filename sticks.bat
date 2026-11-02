@echo off
rem Full 7-piece kit, AR view, drumsticks with red painted tips. Extra arguments are passed through (e.g. --hand-assist).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m spacedrums.app.play --view ar --demo --kit full --red-tips %*
