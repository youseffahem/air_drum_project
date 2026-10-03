# Start this only when the owner is ready for the physical camera test.
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -m spacedrums.app.play --demo @args
exit $LASTEXITCODE
