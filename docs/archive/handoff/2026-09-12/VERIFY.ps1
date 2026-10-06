param(
    [switch]$Full,
    [switch]$SkipPrivateArtifacts
)

$ErrorActionPreference = "Stop"
$failures = [System.Collections.Generic.List[string]]::new()
function Add-Failure([string]$message) {
    $failures.Add($message)
    Write-Host "FAIL: $message" -ForegroundColor Red
}
function Add-Pass([string]$message) {
    Write-Host "PASS: $message" -ForegroundColor Green
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$statePath = Join-Path $PSScriptRoot "CURRENT-STATE.json"
$state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
$actualRoot = (& git -C $repo rev-parse --show-toplevel).Trim().Replace("\", "/")
if ($LASTEXITCODE -ne 0 -or $actualRoot -ne $state.repository) {
    Add-Failure "repository path mismatch: $actualRoot"
} else {
    Add-Pass "repository path"
}
$branch = (& git -C $repo branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne $state.branch) {
    Add-Failure "branch mismatch: $branch"
} else {
    Add-Pass "branch $branch"
}

& git -C $repo show-ref --verify --quiet "refs/tags/$($state.checkpoint_ref)"
if ($LASTEXITCODE -ne 0) {
    Add-Failure "checkpoint tag missing: $($state.checkpoint_ref)"
} else {
    $head = (& git -C $repo rev-parse HEAD).Trim()
    $tagCommit = (& git -C $repo rev-list -n 1 $state.checkpoint_ref).Trim()
    if ($head -ne $tagCommit) {
        Add-Failure "HEAD $head does not match checkpoint $tagCommit"
    } else {
        Add-Pass "checkpoint tag resolves to HEAD $head"
    }
}

$dirty = @(& git -C $repo status --porcelain --untracked-files=all)
if ($dirty.Count -ne 0) {
    Add-Failure "working tree is not clean ($($dirty.Count) entries)"
} else {
    Add-Pass "working tree clean"
}

$hashManifest = Join-Path $PSScriptRoot "FILES.sha256"
$hashLines = Get-Content -LiteralPath $hashManifest -Encoding UTF8
foreach ($line in $hashLines) {
    if (-not $line.Trim()) { continue }
    if ($line.Length -lt 67) {
        Add-Failure "invalid FILES.sha256 line"
        continue
    }
    $expected = $line.Substring(0, 64)
    $relative = $line.Substring(66)
    $path = Join-Path $repo ($relative -replace "/", "\")
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Add-Failure "repository artifact missing: $relative"
        continue
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected) {
        Add-Failure "repository artifact hash mismatch: $relative"
    }
}
if (-not ($failures | Where-Object { $_ -like "repository artifact*" -or $_ -eq "invalid FILES.sha256 line" })) {
    Add-Pass "$($hashLines.Count) repository artifact hashes"
}

if ($SkipPrivateArtifacts) {
    Write-Host "PARTIAL: private artifacts skipped by caller" -ForegroundColor Yellow
} else {
    $privatePath = Join-Path $PSScriptRoot "PRIVATE-ARTIFACTS.json"
    $private = Get-Content -LiteralPath $privatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($artifact in $private.artifacts) {
        if (-not (Test-Path -LiteralPath $artifact.path -PathType Leaf)) {
            Add-Failure "private artifact missing: $($artifact.path)"
            continue
        }
        $item = Get-Item -LiteralPath $artifact.path
        if ($item.Length -ne $artifact.bytes) {
            Add-Failure "private artifact size mismatch: $($artifact.path)"
            continue
        }
        $actual = (Get-FileHash -LiteralPath $artifact.path -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $artifact.sha256) {
            Add-Failure "private artifact hash mismatch: $($artifact.path)"
        }
    }
    if (-not ($failures | Where-Object { $_ -like "private artifact*" })) {
        Add-Pass "$($private.artifacts.Count) private artifact hashes"
    }
}

$python = $state.python
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Add-Failure "pinned Python runtime missing: $python"
} else {
    Add-Pass "pinned Python runtime"
}

Push-Location $repo
try {
    & git diff --check
    if ($LASTEXITCODE -ne 0) {
        Add-Failure "git diff --check"
    } else {
        Add-Pass "git diff --check"
    }
    $env:PYTHONPATH = "src;."
    $env:PYTHONUTF8 = "1"
    $env:PYTHONNOUSERSITE = "1"
    if (Test-Path -LiteralPath $python -PathType Leaf) {
        if ($Full) {
            & $python -m pytest -q -o "addopts="
        } else {
            & $python -m pytest -q -o "addopts=" `
                tests/strategy/test_aa_range_assets_v2.py `
                tests/strategy/test_aa_equity_shadow_v2.py `
                tests/strategy/test_shadow_log.py `
                tests/tools/test_aa8_candidate_v2.py
        }
        if ($LASTEXITCODE -ne 0) {
            Add-Failure "pytest"
        } else {
            $suite = if ($Full) { "full" } else { "smoke" }
            Add-Pass "pytest $suite"
        }
        & $python -m flake8 src tests tools --exclude=aa_record_session.py --statistics --count
        if ($LASTEXITCODE -ne 0) {
            Add-Failure "flake8"
        } else {
            Add-Pass "flake8"
        }
    }
} finally {
    Pop-Location
}

$result = [ordered]@{
    status = if ($failures.Count -eq 0 -and -not $SkipPrivateArtifacts) { "PASS" } elseif ($failures.Count -eq 0) { "PARTIAL" } else { "FAIL" }
    repository = $repo
    checkpoint_ref = $state.checkpoint_ref
    full_tests_requested = [bool]$Full
    private_artifacts_skipped = [bool]$SkipPrivateArtifacts
    failures = @($failures)
}
$result | ConvertTo-Json -Depth 4
if ($failures.Count -ne 0) { exit 1 }
if ($SkipPrivateArtifacts) { exit 2 }
exit 0
