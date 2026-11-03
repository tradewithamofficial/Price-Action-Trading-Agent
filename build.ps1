# Run .\build.ps1 from the source folder; paths resolve relative to this script.
$ErrorActionPreference = 'Stop'
$buildPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    throw 'Create the project environment first: python -m venv .venv'
}
$releaseVersion = 'v1.1.0'
$releaseRoot = Join-Path $PSScriptRoot "release\$releaseVersion"
$releaseFolder = Join-Path $releaseRoot 'PriceActionTradingAgent'
$robotIcon = Join-Path $PSScriptRoot 'assets\TradeWithAM_Robot.ico'
if (-not (Test-Path -LiteralPath $robotIcon)) { throw 'Missing assets\TradeWithAM_Robot.ico' }
if (Test-Path -LiteralPath (Join-Path $releaseFolder 'telegram_config.local.json')) {
    throw 'Move your private Telegram configuration out of the release folder before rebuilding.'
}
$promptRoot = Join-Path $PSScriptRoot 'reference_simple'
foreach ($promptName in @('support_resistance.txt', 'price_action.txt')) {
    $promptPath = Join-Path $promptRoot $promptName
    if (-not (Test-Path -LiteralPath $promptPath) -or
        [string]::IsNullOrWhiteSpace((Get-Content -LiteralPath $promptPath -Raw))) {
        throw "Missing or empty editable prompt: $promptName"
    }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    & $buildPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
    & $buildPython -m PyInstaller --noconfirm --clean --onedir --windowed --name PriceActionTradingAgent `
        --icon $robotIcon `
        --add-data "$(Join-Path $PSScriptRoot 'assets\Futuristic AI Robot with Breakout Chart.png');assets" `
        --add-data "$robotIcon;assets" `
        --add-data "$(Join-Path $promptRoot 'support_resistance.txt');reference_simple" `
        --add-data "$(Join-Path $promptRoot 'price_action.txt');reference_simple" `
        --distpath $releaseRoot `
        --workpath (Join-Path $PSScriptRoot "build\$releaseVersion") `
        --specpath (Join-Path $PSScriptRoot 'build') `
        (Join-Path $PSScriptRoot 'main.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed. See the build output above.' }
    # Generate a blank public template; never copy any local configuration values.
    @{bot_token=''; chat_id=''} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releaseFolder 'telegram_config.example.json') -Encoding utf8
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'RELEASE-SETUP.txt') -Destination $releaseFolder
    $editablePrompts = Join-Path $releaseFolder 'reference_simple'
    New-Item -ItemType Directory -Path $editablePrompts -Force | Out-Null
    foreach ($promptName in @('support_resistance.txt', 'price_action.txt')) {
        Copy-Item -LiteralPath (Join-Path $promptRoot $promptName) -Destination $editablePrompts
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'LICENSE') -Destination $releaseFolder
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'THIRD-PARTY-NOTICES.md') -Destination $releaseFolder
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'third_party_licenses') -Destination $releaseFolder -Recurse -Force
    Write-Host "Created: $(Join-Path $releaseFolder 'PriceActionTradingAgent.exe')"
    Write-Host 'Distribute the complete PriceActionTradingAgent folder, including _internal.'
} finally {
    Pop-Location
}
