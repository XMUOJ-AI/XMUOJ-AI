[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'setup', 'mock', 'status', 'stop', '_backend', '_frontend', '_mock')]
    [string]$Action = 'start',

    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,

    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 8080,

    [string]$PythonPath = '',

    [switch]$ExternalServices,

    [switch]$KeepServices
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = $PSScriptRoot
$BackendDir = Join-Path $ProjectRoot 'backend'
$FrontendDir = Join-Path $ProjectRoot 'frontend'
$VenvDir = Join-Path $ProjectRoot '.venv'
$VenvWindowsPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvMsysPython = Join-Path $VenvDir 'bin\python.exe'
$VenvPython = if (Test-Path -LiteralPath $VenvWindowsPython) {
    $VenvWindowsPython
}
elseif (Test-Path -LiteralPath $VenvMsysPython) {
    $VenvMsysPython
}
else {
    $VenvWindowsPython
}
$StateDir = Join-Path ([System.IO.Path]::GetTempPath()) 'xmuoj-ai-dev'
$StateFile = Join-Path $StateDir 'processes.json'
$PostgresContainer = 'xmuoj-postgres'
$RedisContainer = 'xmuoj-redis'

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    throw $Message
}

function Set-BackendEnvironment {
    $defaults = [ordered]@{
        POSTGRES_HOST = '127.0.0.1'
        POSTGRES_PORT = '5432'
        POSTGRES_DB = 'onlinejudge'
        POSTGRES_USER = 'onlinejudge'
        POSTGRES_PASSWORD = 'onlinejudge'
        REDIS_HOST = '127.0.0.1'
        REDIS_PORT = '6379'
    }
    foreach ($item in $defaults.GetEnumerator()) {
        $current = [Environment]::GetEnvironmentVariable($item.Key, 'Process')
        if ([string]::IsNullOrWhiteSpace($current)) {
            [Environment]::SetEnvironmentVariable($item.Key, $item.Value, 'Process')
        }
    }
}

function Invoke-Native([scriptblock]$Command, [string]$FailureMessage) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Fail $FailureMessage
    }
}

function Test-NativeCommand([scriptblock]$Command) {
    $exitCode = 1
    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Command *> $null
        $exitCode = $LASTEXITCODE
    }
    catch {
        $exitCode = 1
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    return $exitCode -eq 0
}

function Test-ProcessAlive([Nullable[int]]$ProcessId) {
    if (-not $ProcessId) { return $false }
    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Read-ProcessState {
    if (-not (Test-Path -LiteralPath $StateFile)) { return $null }
    try {
        return Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Save-ProcessState($BackendProcess, $FrontendProcess, [string]$Mode) {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
    [ordered]@{
        mode = $Mode
        backend_pid = if ($BackendProcess) { $BackendProcess.Id } else { $null }
        frontend_pid = if ($FrontendProcess) { $FrontendProcess.Id } else { $null }
        backend_port = $BackendPort
        frontend_port = $FrontendPort
        started_at = (Get-Date).ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8
}

function Assert-PortFree([int]$Port, [string]$Label) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $ownerIds = @($listener | Select-Object -ExpandProperty OwningProcess -Unique)
        $owners = foreach ($ownerId in $ownerIds) {
            $process = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
            if ($process) { "$($process.ProcessName) (PID $ownerId)" } else { "PID $ownerId" }
        }
        $ownerText = if ($owners) { $owners -join ', ' } else { 'an unknown process' }
        Fail "$Label port $Port is already in use by $ownerText. Stop that process or choose another port."
    }
}

function Assert-Node {
    if (-not (Get-Command node -ErrorAction SilentlyContinue) -or
        -not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Fail 'Node.js 24 and npm are required. Install them and reopen PowerShell.'
    }
    $version = (& node --version).Trim()
    if ($version -notmatch '^v24\.') {
        Fail "Node.js 24 is required; current version is $version."
    }
}

function Get-Python312Command {
    $candidates = @()
    if ($PythonPath) {
        $candidates += [pscustomobject]@{ File = $PythonPath; Prefix = @(); Source = '-PythonPath' }
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += [pscustomobject]@{ File = 'py'; Prefix = @('-3.12'); Source = 'Python Launcher' }
    }
    if (Get-Command python3.12 -ErrorAction SilentlyContinue) {
        $candidates += [pscustomobject]@{ File = 'python3.12'; Prefix = @(); Source = 'PATH' }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates += [pscustomobject]@{ File = 'python'; Prefix = @(); Source = 'PATH' }
    }

    $commonPaths = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        'C:\Python312\python.exe',
        'D:\Python312\python.exe'
    )
    foreach ($path in $commonPaths) {
        if (Test-Path -LiteralPath $path) {
            $candidates += [pscustomobject]@{ File = $path; Prefix = @(); Source = 'common install path' }
        }
    }

    $attempts = @()
    foreach ($candidate in $candidates) {
        $probeArguments = @($candidate.Prefix) + @('--version')
        $versionOutput = @()
        $probeExitCode = 1
        $previousErrorAction = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $versionOutput = @(& $candidate.File @probeArguments 2>&1)
            $probeExitCode = $LASTEXITCODE
        }
        catch {
            $probeExitCode = 1
            $versionOutput = @($_.Exception.Message)
        }
        finally {
            $ErrorActionPreference = $previousErrorAction
        }
        $versionText = (($versionOutput | ForEach-Object { "$_" }) -join ' ').Trim()
        $attempts += "$($candidate.File) $($candidate.Prefix -join ' '): $versionText"
        if ($probeExitCode -eq 0 -and $versionText -match '^Python 3\.12(?:\.|$)') {
            $platformArguments = @($candidate.Prefix) + @('-c', 'import sysconfig; print(sysconfig.get_platform())')
            $platformOutput = @()
            $platformExitCode = 1
            $previousErrorAction = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                $platformOutput = @(& $candidate.File @platformArguments 2>&1)
                $platformExitCode = $LASTEXITCODE
            }
            catch {
                $platformExitCode = 1
                $platformOutput = @($_.Exception.Message)
            }
            finally {
                $ErrorActionPreference = $previousErrorAction
            }
            $platformText = (($platformOutput | ForEach-Object { "$_" }) -join ' ').Trim()
            if ($platformExitCode -eq 0 -and $platformText -match '^win-') {
                return $candidate
            }
            $attempts += "  rejected platform: $platformText (standard Windows CPython is required)"
        }
    }
    if ($attempts.Count -gt 0) {
        Write-Verbose ("Python candidates checked:`n  " + ($attempts -join "`n  "))
    }
    return $null
}

function Ensure-PythonEnvironment {
    if (-not (Test-Path -LiteralPath $VenvWindowsPython) -and
        -not (Test-Path -LiteralPath $VenvMsysPython)) {
        Write-Step 'Creating the Python 3.12 virtual environment'
        $python312 = Get-Python312Command
        if (-not $python312) {
            $currentVersion = 'not found'
            if (Get-Command python -ErrorAction SilentlyContinue) {
                $detected = & python --version 2>&1
                if ($LASTEXITCODE -eq 0) { $currentVersion = "$detected".Trim() }
            }
            Fail @"
Standard Windows CPython 3.12 is not installed or cannot be found. Current 'python' command: $currentVersion.
MSYS2/MinGW Python is not supported because Pillow, psycopg2, and lxml do not provide compatible wheels.
Install a Python 3.12.x 64-bit release from python.org or create a Windows conda Python 3.12 environment.
If Python 3.12 is already installed in a custom directory, run:
  .\dev.ps1 start -PythonPath 'C:\path\to\Python312\python.exe'
"@
        }
        $venvArguments = @($python312.Prefix) + @('-m', 'venv', $VenvDir)
        Invoke-Native { & $python312.File @venvArguments } "Failed to create the Python 3.12 virtual environment with $($python312.Source)."
    }

    if (Test-Path -LiteralPath $VenvWindowsPython) {
        $script:VenvPython = $VenvWindowsPython
    }
    elseif (Test-Path -LiteralPath $VenvMsysPython) {
        $script:VenvPython = $VenvMsysPython
    }
    else {
        Fail "The virtual environment was created without a usable python.exe under '$VenvDir'."
    }

    $pythonVersionOutput = @(& $VenvPython --version 2>&1)
    $pythonVersionExitCode = $LASTEXITCODE
    $pythonVersion = (($pythonVersionOutput | ForEach-Object { "$_" }) -join ' ').Trim()
    if ($pythonVersionExitCode -ne 0 -or $pythonVersion -notmatch '^Python 3\.12(?:\.|$)') {
        Fail "The existing .venv is not using Python 3.12 (detected: $pythonVersion). Remove it and recreate it with Python 3.12."
    }

    $pythonPlatformOutput = @(& $VenvPython -c 'import sysconfig; print(sysconfig.get_platform())' 2>&1)
    $pythonPlatformExitCode = $LASTEXITCODE
    $pythonPlatform = (($pythonPlatformOutput | ForEach-Object { "$_" }) -join ' ').Trim()
    if ($pythonPlatformExitCode -ne 0 -or $pythonPlatform -notmatch '^win-') {
        Fail @"
The existing .venv uses an unsupported Python platform: $pythonPlatform.
This MSYS2/MinGW environment cannot install the required Pillow, psycopg2, and lxml wheels.
Install standard Windows CPython 3.12, remove '$VenvDir', then run dev.ps1 again with -PythonPath.
"@
    }

    $dependencyProbeExitCode = 1
    $dependencyProbeOutput = @()
    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $dependencyProbeOutput = @(& $VenvPython -c 'import django, rest_framework, psycopg2, redis; print(redis.__version__)' 2>$null)
        $dependencyProbeExitCode = $LASTEXITCODE
    }
    catch {
        $dependencyProbeExitCode = 1
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    $installedRedisVersion = (($dependencyProbeOutput | ForEach-Object { "$_" }) -join ' ').Trim()
    if ($dependencyProbeExitCode -eq 0 -and $installedRedisVersion -ne '5.0.8') {
        $dependencyProbeExitCode = 1
    }
    if ($dependencyProbeExitCode -ne 0) {
        Write-Step 'Installing backend dependencies from the locked requirements file'
        Invoke-Native {
            & $VenvPython -m pip install -r (Join-Path $BackendDir 'deploy\requirements.txt')
        } 'Backend dependency installation failed.'
    }
}

function Ensure-FrontendDependencies {
    Assert-Node
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir 'node_modules'))) {
        Write-Step 'Installing frontend dependencies from package-lock.json'
        Push-Location $FrontendDir
        try {
            Invoke-Native { & npm ci } 'Frontend dependency installation failed.'
        }
        finally {
            Pop-Location
        }
    }
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail 'Docker Desktop is required for real-backend mode. Install and start Docker Desktop first.'
    }
    if (-not (Test-NativeCommand { & docker info })) {
        Fail 'Docker Desktop is installed but is not running.'
    }
}

function Test-ContainerExists([string]$Name) {
    return Test-NativeCommand { & docker inspect $Name }
}

function Test-ContainerRunning([string]$Name) {
    if (-not (Test-ContainerExists $Name)) { return $false }
    return ((& docker inspect -f '{{.State.Running}}' $Name).Trim() -eq 'true')
}

function Test-TcpEndpoint([string]$Address, [int]$Port, [int]$TimeoutMilliseconds = 2500) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($Address, $Port)
        if (-not $task.Wait($TimeoutMilliseconds)) { return $false }
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Ensure-ExternalDataServices {
    Write-Step 'Checking externally managed PostgreSQL and Redis'
    $postgresPortNumber = [int]$env:POSTGRES_PORT
    $redisPortNumber = [int]$env:REDIS_PORT

    if (-not (Test-TcpEndpoint $env:POSTGRES_HOST $postgresPortNumber)) {
        Fail "PostgreSQL is not reachable at $($env:POSTGRES_HOST):$postgresPortNumber. Start it first or correct the POSTGRES_* environment variables."
    }
    if (-not (Test-TcpEndpoint $env:REDIS_HOST $redisPortNumber)) {
        Fail "Redis is not reachable at $($env:REDIS_HOST):$redisPortNumber. Start it first or correct the REDIS_* environment variables."
    }
    Write-Host 'External PostgreSQL and Redis ports are reachable.'
}

function Ensure-DataServices {
    Assert-Docker

    if (-not (Test-ContainerExists $PostgresContainer)) {
        Write-Step 'Creating the PostgreSQL development container'
        Invoke-Native {
            & docker run --name $PostgresContainer `
                -e POSTGRES_DB=onlinejudge `
                -e POSTGRES_USER=onlinejudge `
                -e POSTGRES_PASSWORD=onlinejudge `
                -p 5432:5432 `
                -v xmuoj-postgres-data:/var/lib/postgresql/data `
                -d postgres:16
        } 'Failed to create the PostgreSQL container.'
    }
    elseif (-not (Test-ContainerRunning $PostgresContainer)) {
        Write-Step 'Starting the PostgreSQL development container'
        Invoke-Native { & docker start $PostgresContainer } 'Failed to start the PostgreSQL container.'
    }

    if (-not (Test-ContainerExists $RedisContainer)) {
        Write-Step 'Creating the Redis development container'
        Invoke-Native {
            & docker run --name $RedisContainer -p 6379:6379 -d redis:7-alpine
        } 'Failed to create the Redis container.'
    }
    elseif (-not (Test-ContainerRunning $RedisContainer)) {
        Write-Step 'Starting the Redis development container'
        Invoke-Native { & docker start $RedisContainer } 'Failed to start the Redis container.'
    }

    Write-Step 'Waiting for PostgreSQL and Redis'
    $postgresReady = $false
    $redisReady = $false
    foreach ($attempt in 1..45) {
        $postgresReady = Test-NativeCommand { & docker exec $PostgresContainer pg_isready -U onlinejudge -d onlinejudge }
        $redisReady = Test-NativeCommand { & docker exec $RedisContainer redis-cli ping }
        if ($postgresReady -and $redisReady) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $postgresReady -or -not $redisReady) {
        Fail 'PostgreSQL or Redis did not become ready within 45 seconds.'
    }
}

function Ensure-SecretKey {
    $configDir = Join-Path $BackendDir 'data\config'
    $keyPath = Join-Path $configDir 'secret.key'
    if (Test-Path -LiteralPath $keyPath) { return }

    Write-Step 'Creating backend/data/config/secret.key'
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    $bytes = New-Object byte[] 48
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    [System.IO.File]::WriteAllText($keyPath, [Convert]::ToBase64String($bytes))
}

function Initialize-RealEnvironment {
    Ensure-PythonEnvironment
    Ensure-FrontendDependencies
    Ensure-SecretKey
    Set-BackendEnvironment
    if ($ExternalServices) {
        Ensure-ExternalDataServices
    }
    else {
        Ensure-DataServices
    }

    Write-Step 'Applying database migrations'
    Push-Location $BackendDir
    try {
        Invoke-Native { & $VenvPython manage.py migrate } 'Database migration failed.'
    }
    finally {
        Pop-Location
    }
}

function Start-ChildProcess([string]$ChildAction, [string]$Title) {
    $arguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $PSCommandPath),
        $ChildAction,
        '-BackendPort', $BackendPort,
        '-FrontendPort', $FrontendPort
    )
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -PassThru
    Write-Host "$Title process started (PID $($process.Id))."
    return $process
}

function Stop-TrackedProcess([Nullable[int]]$ProcessId, [string]$Label) {
    if (-not (Test-ProcessAlive $ProcessId)) {
        Write-Host "$Label is not running."
        return
    }

    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    if (-not $processInfo -or $processInfo.CommandLine -notlike '*dev.ps1*') {
        Write-Warning "PID $ProcessId no longer belongs to dev.ps1; it was not stopped."
        return
    }

    & taskkill /PID $ProcessId /T /F *> $null
    Write-Host "$Label stopped."
}

function Show-Status {
    $state = Read-ProcessState
    if ($state) {
        $backendStatus = if (Test-ProcessAlive $state.backend_pid) { 'running' } else { 'stopped' }
        $frontendStatus = if (Test-ProcessAlive $state.frontend_pid) { 'running' } else { 'stopped' }
        Write-Host "Mode:     $($state.mode)"
        Write-Host "Backend:  $backendStatus (PID $($state.backend_pid), port $($state.backend_port))"
        Write-Host "Frontend: $frontendStatus (PID $($state.frontend_pid), port $($state.frontend_port))"
    }
    else {
        Write-Host 'No frontend or backend process state was found.'
    }

    if (Get-Command docker -ErrorAction SilentlyContinue) {
        $postgresStatus = if (Test-ContainerRunning $PostgresContainer) { 'running' } else { 'stopped or missing' }
        $redisStatus = if (Test-ContainerRunning $RedisContainer) { 'running' } else { 'stopped or missing' }
        Write-Host "PostgreSQL: $postgresStatus"
        Write-Host "Redis:      $redisStatus"
    }
}

if ($Action -eq '_backend') {
    $Host.UI.RawUI.WindowTitle = 'XMUOJ Backend'
    Set-Location $BackendDir
    & $VenvPython manage.py runserver "127.0.0.1:$BackendPort"
    exit $LASTEXITCODE
}

if ($Action -eq '_frontend') {
    $Host.UI.RawUI.WindowTitle = 'XMUOJ Frontend'
    $env:TARGET = "http://127.0.0.1:$BackendPort"
    $env:PORT = "$FrontendPort"
    Set-Location $FrontendDir
    & npm run dev
    exit $LASTEXITCODE
}

if ($Action -eq '_mock') {
    $Host.UI.RawUI.WindowTitle = 'XMUOJ Frontend Mock'
    $env:PORT = "$FrontendPort"
    Set-Location $FrontendDir
    & npm run dev:mock
    exit $LASTEXITCODE
}

switch ($Action) {
    'setup' {
        Initialize-RealEnvironment
        Write-Host "`nSetup completed. Run '.\dev.ps1 start' to launch the application." -ForegroundColor Green
    }

    'start' {
        $oldState = Read-ProcessState
        if ($oldState -and ((Test-ProcessAlive $oldState.backend_pid) -or (Test-ProcessAlive $oldState.frontend_pid))) {
            Fail "A tracked development process is already running. Run '.\dev.ps1 status' or '.\dev.ps1 stop' first."
        }

        Initialize-RealEnvironment
        Assert-PortFree $BackendPort 'Backend'
        Assert-PortFree $FrontendPort 'Frontend'

        Write-Step 'Starting backend and frontend in separate PowerShell windows'
        $backendProcess = Start-ChildProcess '_backend' 'Backend'
        Start-Sleep -Seconds 2
        $frontendProcess = Start-ChildProcess '_frontend' 'Frontend'
        $runMode = if ($ExternalServices) { 'real-external' } else { 'real-docker' }
        Save-ProcessState $backendProcess $frontendProcess $runMode

        Write-Host "`nDevelopment environment started." -ForegroundColor Green
        Write-Host "Main site:       http://127.0.0.1:$FrontendPort/"
        Write-Host "Knowledge pages: http://127.0.0.1:$FrontendPort/knowledge"
        Write-Host "Admin login:     http://127.0.0.1:$FrontendPort/admin/login"
        Write-Host "Stop everything: .\dev.ps1 stop"
    }

    'mock' {
        $oldState = Read-ProcessState
        if ($oldState -and ((Test-ProcessAlive $oldState.backend_pid) -or (Test-ProcessAlive $oldState.frontend_pid))) {
            Fail "A tracked development process is already running. Run '.\dev.ps1 stop' first."
        }

        Ensure-FrontendDependencies
        Assert-PortFree $FrontendPort 'Frontend'
        Write-Step 'Starting the frontend Mock server'
        $frontendProcess = Start-ChildProcess '_mock' 'Frontend Mock'
        Save-ProcessState $null $frontendProcess 'mock'
        Write-Host "`nMock environment started at http://127.0.0.1:$FrontendPort/" -ForegroundColor Green
        Write-Host "Stop it with: .\dev.ps1 stop"
    }

    'status' {
        Show-Status
    }

    'stop' {
        $state = Read-ProcessState
        if ($state) {
            Stop-TrackedProcess $state.backend_pid 'Backend'
            Stop-TrackedProcess $state.frontend_pid 'Frontend'
            Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
        }
        else {
            Write-Host 'No tracked frontend or backend processes were found.'
        }

        $usesExternalServices = $state -and $state.mode -eq 'real-external'
        if (-not $KeepServices -and -not $usesExternalServices -and (Get-Command docker -ErrorAction SilentlyContinue)) {
            foreach ($container in @($PostgresContainer, $RedisContainer)) {
                if (Test-ContainerRunning $container) {
                    & docker stop $container | Out-Null
                    Write-Host "$container stopped."
                }
            }
        }
        elseif ($KeepServices) {
            Write-Host 'PostgreSQL and Redis were left running.'
        }
        elseif ($usesExternalServices) {
            Write-Host 'Externally managed PostgreSQL and Redis were not stopped.'
        }
    }
}
