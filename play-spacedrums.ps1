Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -m spacedrums.app.play @args
exit $LASTEXITCODE
