$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $projectRoot ".uv-cache"

Push-Location $projectRoot
try {
    Invoke-Checked { uv sync --frozen }
    Invoke-Checked { uv run --frozen ruff check . }
    Invoke-Checked { uv run --frozen pytest }
    Invoke-Checked { uv run --frozen python -m compileall -q src scripts tests }
}
finally {
    Pop-Location
}
