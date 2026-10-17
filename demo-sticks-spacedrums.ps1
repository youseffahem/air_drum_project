# Red painted stick tips: both painted caps tracked by redness (a MARKER condition, see docs/perf/red-tip-stick-mode.md).
# Start this only when the owner is ready for the physical camera test.
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -m spacedrums.app.play --demo --red-tips @args
exit $LASTEXITCODE
