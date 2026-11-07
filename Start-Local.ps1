[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [switch]$NoBrowser,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv-local\Scripts\python.exe"

function Set-ApplicationUrls {
    param([int]$SelectedPort)

    $script:AppUrl = "http://127.0.0.1:$SelectedPort/"
    $script:HealthUrl = "http://127.0.0.1:$SelectedPort/health"
}

Set-ApplicationUrls -SelectedPort $Port

function Test-ApplicationReady {
    param([string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Test-FrontendReady {
    param([string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        $policy = $response.Headers["Content-Security-Policy"]
        return $response.StatusCode -eq 200 -and
            $response.Content -match "Campus Medical Assistance" -and
            $policy -match "script-src 'self'"
    }
    catch {
        return $false
    }
}

function Test-PortInUse {
    param([int]$PortToCheck)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $PortToCheck)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Find-AvailablePort {
    param([int]$StartingPort)

    for ($candidate = $StartingPort; $candidate -le ($StartingPort + 20); $candidate++) {
        if (-not (Test-PortInUse -PortToCheck $candidate)) {
            return $candidate
        }
    }
    throw "No free local port was found between $StartingPort and $($StartingPort + 20)."
}

function Get-PythonExecutable {
    if (Test-Path -LiteralPath $VenvPython) {
        return $VenvPython
    }

    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue

    if ($pythonLauncher) {
        Write-Host "Creating the local Python environment..." -ForegroundColor Cyan
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $pythonLauncher.Source -3.11 -c "import sys" 2>$null
        $hasPython311 = $LASTEXITCODE -eq 0
        if (-not $hasPython311) {
            & $pythonLauncher.Source -3.12 -c "import sys" 2>$null
            $hasPython312 = $LASTEXITCODE -eq 0
        }
        $ErrorActionPreference = $previousErrorActionPreference

        if ($hasPython311) {
            & $pythonLauncher.Source -3.11 -m venv (Join-Path $ProjectRoot ".venv-local")
        }
        elseif ($hasPython312) {
            & $pythonLauncher.Source -3.12 -m venv (Join-Path $ProjectRoot ".venv-local")
        }
        else {
            throw "Python 3.11 or 3.12 was not found. Install one of those versions, then run this launcher again."
        }
    }
    else {
        throw "The Python Launcher was not found. Install Python 3.11, including the Python Launcher, then run this launcher again."
    }

    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "The virtual environment could not be created."
    }

    return $VenvPython
}

function Initialize-EnvironmentFile {
    $envFile = Join-Path $ProjectRoot ".env"
    if (Test-Path -LiteralPath $envFile) {
        return
    }

    $templateFile = Join-Path $ProjectRoot ".env.example"
    if (-not (Test-Path -LiteralPath $templateFile)) {
        throw "Neither .env nor .env.example was found."
    }

    Copy-Item -LiteralPath $templateFile -Destination $envFile
    $randomBytes = New-Object byte[] 48
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($randomBytes)
    $jwtSecret = [Convert]::ToBase64String($randomBytes)
    $envContent = Get-Content -LiteralPath $envFile -Raw
    $envContent = $envContent -replace '(?m)^APP_NAME=.*$', "APP_NAME=Campus Medical Assistance"
    $envContent = $envContent -replace '(?m)^JWT_SECRET=.*$', "JWT_SECRET=$jwtSecret"
    Set-Content -LiteralPath $envFile -Value $envContent -Encoding utf8
    Write-Host "Created .env with a local JWT secret." -ForegroundColor Green
}

Set-Location -LiteralPath $ProjectRoot
Initialize-EnvironmentFile
$Python = Get-PythonExecutable

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python -c "import fastapi, uvicorn, sqlalchemy, pydantic_settings, slowapi, structlog, redis, jwt, pwdlib, PIL, prometheus_client" 2>$null
$dependenciesInstalled = $LASTEXITCODE -eq 0
$ErrorActionPreference = $previousErrorActionPreference

if (-not $dependenciesInstalled) {
    Write-Host "Installing Python dependencies (first run only)..." -ForegroundColor Cyan
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed. Review the error above and run the launcher again."
    }
}

if ((Test-ApplicationReady -Url $HealthUrl) -and (Test-FrontendReady -Url $AppUrl)) {
    Write-Host "Campus Medical Assistance is already running at $AppUrl" -ForegroundColor Green
    if (-not $NoBrowser) {
        Start-Process $AppUrl
    }
    return
}

if (Test-PortInUse -PortToCheck $Port) {
    $originalPort = $Port
    $Port = Find-AvailablePort -StartingPort ($Port + 1)
    Set-ApplicationUrls -SelectedPort $Port
    Write-Host "Port $originalPort is already in use. Starting this project on port $Port instead." -ForegroundColor Yellow
}

if ($CheckOnly) {
    Write-Host "Local setup is ready. The app will start at $AppUrl" -ForegroundColor Green
    return
}

Write-Host "Starting Campus Medical Assistance at $AppUrl" -ForegroundColor Green
$server = Start-Process -FilePath $Python -ArgumentList @(
    "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port", "--reload"
) -WorkingDirectory $ProjectRoot -PassThru -NoNewWindow
$worker = $null

try {
    $ready = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-ApplicationReady -Url $HealthUrl) {
            $ready = $true
            break
        }
        if ($server.HasExited) {
            throw "The server stopped before it became ready."
        }
    }

    if (-not $ready) {
        throw "The server did not become ready within 30 seconds."
    }

    if (-not $NoBrowser) {
        Start-Process $AppUrl
    }

    $worker = Start-Process -FilePath $Python -ArgumentList @(
        "-m", "app.worker"
    ) -WorkingDirectory $ProjectRoot -PassThru -WindowStyle Hidden

    Write-Host "The app and local notification worker are running. Press Ctrl+C in this window to stop them." -ForegroundColor Yellow
    Wait-Process -Id $server.Id
}
finally {
    if ($worker -and -not $worker.HasExited) {
        Stop-Process -Id $worker.Id -Force
    }
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
}
