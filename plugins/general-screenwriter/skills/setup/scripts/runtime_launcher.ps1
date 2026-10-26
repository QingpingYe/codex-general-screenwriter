param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Script,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArguments
)

$ErrorActionPreference = 'Stop'

function Write-LauncherError {
    param(
        [string]$Status,
        [string]$Message
    )
    $payload = [ordered]@{
        schema_version = 1
        status = $Status
        ready = $false
        reason_code = $Status
        message = $Message
    }
    Write-Output ($payload | ConvertTo-Json -Compress)
}

function Resolve-PythonCandidate {
    param([string]$Candidate)
    if ([string]::IsNullOrWhiteSpace($Candidate)) {
        return $null
    }
    try {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    catch {
        return $null
    }
    $command = Get-Command $Candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $command) {
        return $null
    }
    if ($command.Path) {
        return $command.Path
    }
    return $command.Source
}

function Test-PythonCandidate {
    param([string]$Candidate)
    if ([string]::IsNullOrWhiteSpace($Candidate)) {
        return $false
    }
    try {
        & $Candidate -I -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

$scriptPath = Resolve-PythonCandidate $Script
if ([string]::IsNullOrWhiteSpace($scriptPath)) {
    Write-LauncherError 'script_missing' 'the requested setup script does not exist'
    exit 2
}

$candidates = New-Object System.Collections.Generic.List[string]
$hostCandidates = @(
    $env:GENERAL_SCREENWRITER_HOST_PYTHON,
    $env:CODEX_PYTHON,
    $env:PYTHON
)
foreach ($candidate in $hostCandidates) {
    if (-not [string]::IsNullOrWhiteSpace($candidate)) {
        $candidates.Add($candidate)
    }
}

$systemCandidates = @(
    $env:GENERAL_SCREENWRITER_SYSTEM_PYTHON,
    'python',
    'python3'
)
foreach ($candidate in $systemCandidates) {
    if (-not [string]::IsNullOrWhiteSpace($candidate)) {
        $candidates.Add($candidate)
    }
}

$userCandidates = New-Object System.Collections.Generic.List[string]
if (-not [string]::IsNullOrWhiteSpace($env:GENERAL_SCREENWRITER_USER_PYTHON)) {
    $userCandidates.Add($env:GENERAL_SCREENWRITER_USER_PYTHON)
}
if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
    $userCandidates.Add((Join-Path $env:USERPROFILE '.local\bin\python.exe'))
    $userCandidates.Add((Join-Path $env:USERPROFILE '.local\bin\python3.exe'))
}
if (-not [string]::IsNullOrWhiteSpace($env:GENERAL_SCREENWRITER_USER_DATA)) {
    $userCandidates.Add((Join-Path $env:GENERAL_SCREENWRITER_USER_DATA 'general-screenwriter\runtimes\python\python.exe'))
}
if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    try {
        $userCandidates.AddRange([string[]](Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe') -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -ExpandProperty FullName))
    }
    catch {
        # Candidate discovery is best effort; the canonical error remains runtime_missing.
    }
}
foreach ($candidate in $userCandidates) {
    if (-not [string]::IsNullOrWhiteSpace($candidate)) {
        $candidates.Add($candidate)
    }
}

$selected = $null
foreach ($candidate in $candidates) {
    $resolved = Resolve-PythonCandidate $candidate
    if ((Test-PythonCandidate $resolved)) {
        $selected = $resolved
        break
    }
}

if ([string]::IsNullOrWhiteSpace($selected)) {
    Write-LauncherError 'runtime_missing' 'no compatible host, system, or user Python interpreter was found'
    exit 2
}

& $selected -I $scriptPath @ScriptArguments
exit $LASTEXITCODE
