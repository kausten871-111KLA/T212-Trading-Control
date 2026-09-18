$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Open WebUI + Alpaca market-data activation (local / DEMO)" -ForegroundColor Cyan
Write-Host "Secrets are entered locally and are not printed." -ForegroundColor DarkGray
Write-Host ""

$alpacaKeySecure = Read-Host "Alpaca API key" -AsSecureString
$alpacaSecretSecure = Read-Host "Alpaca API secret" -AsSecureString

$env:ALPACA_API_KEY = (New-Object System.Net.NetworkCredential("", $alpacaKeySecure)).Password
$env:ALPACA_API_SECRET = (New-Object System.Net.NetworkCredential("", $alpacaSecretSecure)).Password

if (-not $env:ALPACA_API_KEY -or -not $env:ALPACA_API_SECRET) {
    throw "Alpaca credentials were not loaded."
}

Write-Host "ALPACA MARKET DATA CREDENTIALS LOADED" -ForegroundColor Green

$requiredExisting = @(
    "T212_DEMO_API_KEY",
    "T212_DEMO_API_SECRET",
    "OPENWEBUI_ADMIN_API_KEY"
)

foreach ($name in $requiredExisting) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    if (-not $value) {
        Write-Warning "$name is not present in this PowerShell process. Existing T212/Configurator functions may not work after restart until that variable is loaded."
    }
}

$env:DATA_DIR = "C:\Users\katie\open-webui-data"

Write-Host ""
Write-Host "Starting Open WebUI at http://localhost:8080" -ForegroundColor Cyan
Write-Host "Keep this PowerShell window open while Open WebUI is running." -ForegroundColor DarkGray
Write-Host ""

uvx --python 3.11 open-webui@latest serve
