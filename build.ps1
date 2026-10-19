# Run .\build.ps1 from the source folder; paths resolve relative to this script.
$ErrorActionPreference = 'Stop'
$buildPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    throw 'Create the project environment first: python -m venv .venv'
}
$releaseFolder = Join-Path $PSScriptRoot 'release\PriceActionTradingAgent'
$robotIcon = Join-Path $PSScriptRoot 'assets\TradeWithAM_Robot.ico'
if (-not (Test-Path -LiteralPath $robotIcon)) { throw 'Missing assets\TradeWithAM_Robot.ico' }
if (Test-Path -LiteralPath (Join-Path $releaseFolder 'telegram_config.local.json')) {
    throw 'Move your private Telegram configuration out of the release folder before rebuilding.'
}
$examplePath = Join-Path $PSScriptRoot 'telegram_config.example.json'
$exampleConfig = Get-Content -LiteralPath $examplePath -Raw | ConvertFrom-Json
if ($exampleConfig.bot_token -ne '' -or $exampleConfig.chat_id -ne '' -or
    @($exampleConfig.PSObject.Properties).Count -ne 2) {
    throw 'telegram_config.example.json must contain only blank bot_token and chat_id fields.'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    & $buildPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
    & $buildPython -m PyInstaller --noconfirm --clean --onedir --windowed --name PriceActionTradingAgent `
        --icon $robotIcon `
        --add-data "$(Join-Path $PSScriptRoot 'assets\Futuristic AI Robot with Breakout Chart.png');assets" `
        --add-data "$robotIcon;assets" `
        --distpath (Join-Path $PSScriptRoot 'release') `
        --workpath (Join-Path $PSScriptRoot 'build') `
        --specpath (Join-Path $PSScriptRoot 'build') `
        (Join-Path $PSScriptRoot 'main.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed. See the build output above.' }
    Copy-Item -LiteralPath $examplePath -Destination (Join-Path $releaseFolder 'telegram_config.example.json')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'RELEASE-SETUP.txt') -Destination (Join-Path $releaseFolder 'README-SETUP.txt')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'LICENSE') -Destination $releaseFolder
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'THIRD-PARTY-NOTICES.md') -Destination $releaseFolder
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'third_party_licenses') -Destination $releaseFolder -Recurse -Force
    Write-Host "Created: $(Join-Path $releaseFolder 'PriceActionTradingAgent.exe')"
    Write-Host 'Distribute the complete PriceActionTradingAgent folder, including _internal.'
} finally {
    Pop-Location
}
