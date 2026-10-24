# AR view: the GPU-rendered 3D kit over the live camera (ADR-0049). Add --demo, --fingers, --red-tips as usual.
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -m spacedrums.app.play --view ar @args
exit $LASTEXITCODE
