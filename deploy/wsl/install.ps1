# OIW Installation — WSL2 PowerShell wrapper
# WP-06 Track F Task F-002
# Run in PowerShell (Admin): .\deploy\wsl\install.ps1

Write-Host "=== OIW Installer (WSL2) ===" -ForegroundColor Cyan

# Check WSL
$wsl = wsl --list --running 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: WSL2 not found. Install: wsl --install" -ForegroundColor Red
    exit 1
}

Write-Host "✓ WSL2 detected"

# Run the Linux installer inside WSL
$repoPath = (Get-Item .).FullName
$wslPath = ($repoPath -replace 'C:', '/mnt/c') -replace '\\', '/'

Write-Host "Running installer in WSL..."
wsl bash -c "cd '$wslPath' && bash deploy/install-linux.sh"

Write-Host ""
Write-Host "=== Installation Complete ===" -ForegroundColor Green
Write-Host "  Web UI:  http://localhost:5173"
Write-Host "  API:     http://localhost:8000/docs"
