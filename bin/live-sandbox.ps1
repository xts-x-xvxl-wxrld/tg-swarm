param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("poll", "api", "scheduler", "listener", "executor", "reviewer")]
    [string]$Role,

    [string]$SandboxName = "live-telegram",

    [string]$SandboxRoot = "",

    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Repair-PathEnvironment {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $combined = @($machinePath, $userPath) -join ";"
    $combined = ($combined -split ";" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique) -join ";"

    if ([string]::IsNullOrWhiteSpace($env:Path) -and -not [string]::IsNullOrWhiteSpace($combined)) {
        $env:Path = $combined
    }
    if ([string]::IsNullOrWhiteSpace($env:PATH) -and -not [string]::IsNullOrWhiteSpace($env:Path)) {
        $env:PATH = $env:Path
    }

    if ($env:PATH -and $env:Path -and $env:PATH -ne $env:Path) {
        $env:PATH = $env:Path
    }
}

Repair-PathEnvironment

function Initialize-EnvFromDotEnv {
    param(
        [string]$FilePath
    )

    if (-not (Test-Path $FilePath)) {
        return
    }

    foreach ($line in Get-Content $FilePath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2) {
            continue
        }
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ([string]::IsNullOrWhiteSpace($name)) {
            continue
        }
        $existing = [Environment]::GetEnvironmentVariable($name)
        if ([string]::IsNullOrWhiteSpace($existing)) {
            [Environment]::SetEnvironmentVariable($name, $value)
        }
    }
}

Initialize-EnvFromDotEnv -FilePath (Join-Path $repoRoot ".env")

function Resolve-PythonExecutable {
    $candidates = @(
        "C:\Python314\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        return $pyCommand.Source
    }
    throw "Could not find a Python executable for sandbox launch."
}

if (-not $SandboxRoot) {
    $SandboxRoot = Join-Path $repoRoot ".sandbox\$SandboxName"
}

$stateDir = Join-Path $SandboxRoot "state"
$dataDir = Join-Path $SandboxRoot "data"
$monitoringDir = Join-Path $SandboxRoot "monitoring"

New-Item -ItemType Directory -Force -Path $SandboxRoot | Out-Null
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
New-Item -ItemType Directory -Force -Path $monitoringDir | Out-Null

$env:TELEGRAM_CAPABILITY_BACKEND = "telethon"
$env:TELEGRAM_RUNTIME_STATE_DIR = $stateDir
$env:TG_SWARM_DATA_DIR = $dataDir
$env:TG_SWARM_MONITORING_DIR = $monitoringDir
$env:PORT = "$Port"
if ($Role -eq "poll") {
    Remove-Item Env:TG_SWARM_MTPROTO_SESSION_NAMESPACE -ErrorAction SilentlyContinue
} else {
    $env:TG_SWARM_MTPROTO_SESSION_NAMESPACE = $Role
}

$requiredVars = @(
    "ANTHROPIC_API_KEY",
    "DEFAULT_MODEL",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH"
)

if ($Role -eq "poll" -or $Role -eq "api") {
    $requiredVars += "TELEGRAM_BOT_TOKEN"
}

$missingVars = @()
foreach ($name in $requiredVars) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        $missingVars += $name
    }
}

if ($missingVars.Count -gt 0) {
    throw "Missing required environment variables for sandbox launch: $($missingVars -join ', ')"
}

$pythonArgs = switch ($Role) {
    "poll" { @("server.py", "--poll") }
    "api" { @("server.py") }
    "scheduler" { @("server.py", "--run-scheduler") }
    "listener" { @("server.py", "--run-engagement-listener") }
    "executor" { @("server.py", "--run-live-executor") }
    "reviewer" { @("server.py", "--run-conversation-reviewer") }
}
$pythonArgs = @($pythonArgs)
$pythonExe = Resolve-PythonExecutable

Write-Host "tg-swarm live sandbox launcher"
Write-Host "  backend: telethon (forced)"
Write-Host "  role: $Role"
Write-Host "  sandbox: $SandboxName"
Write-Host "  state dir: $stateDir"
Write-Host "  data dir: $dataDir"
Write-Host "  monitoring dir: $monitoringDir"
if ($Role -eq "api") {
    Write-Host "  port: $Port"
}

& $pythonExe @pythonArgs
