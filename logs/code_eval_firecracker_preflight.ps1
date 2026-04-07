$ErrorActionPreference = 'Stop'

$repoRoot = 'd:/dev/DEP'
$base = 'http://localhost:8080/api/v1'
$date = Get-Date -Format 'yyyy-MM-dd'
$logPath = "d:/dev/DEP/logs/code_eval_firecracker_preflight_$date.txt"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 's'), $Message
    Add-Content -Path $logPath -Value $line -Encoding UTF8
    Write-Output $line
}

function Clear-OverrideEnvs {
    $names = @(
        'CODE_EVAL_EXECUTION_BACKEND',
        'CODE_EVAL_MICROVM_ENABLE_ADAPTER',
        'CODE_EVAL_MICROVM_RUNTIME_MODE',
        'CODE_EVAL_MICROVM_ALLOW_FALLBACK'
    )
    foreach ($name in $names) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
}

Set-Location $repoRoot
"Code Eval Firecracker Runtime Preflight`nDate: $date`n" | Set-Content -Path $logPath -Encoding UTF8

try {
    Write-Log 'Switching backend/worker to microvm firecracker_vsock mode (fallback disabled).'
    $env:CODE_EVAL_EXECUTION_BACKEND = 'microvm'
    $env:CODE_EVAL_MICROVM_ENABLE_ADAPTER = 'true'
    $env:CODE_EVAL_MICROVM_RUNTIME_MODE = 'firecracker_vsock'
    $env:CODE_EVAL_MICROVM_ALLOW_FALLBACK = 'false'
    docker compose up -d --force-recreate backend worker-code-eval | Out-Null

    for ($i=0; $i -lt 50; $i++) {
        try {
            $h = Invoke-RestMethod -Method Get -Uri 'http://localhost:8080/health'
            if ($h.status -eq 'ok') { break }
        } catch {}
        Start-Sleep -Seconds 1
    }

    $runtimeStatus = Invoke-RestMethod -Method Get -Uri "$base/code-eval/runtime/status"
    $preflight = Invoke-RestMethod -Method Get -Uri "$base/code-eval/runtime/preflight"

    Write-Log ("runtime_status=" + ($runtimeStatus | ConvertTo-Json -Depth 12 -Compress))
    Write-Log ("runtime_preflight=" + ($preflight | ConvertTo-Json -Depth 12 -Compress))

    $ready = $false
    if ($preflight.firecracker -and $preflight.firecracker.ready -eq $true) {
        $ready = $true
    }

    if ($ready) {
        Write-Log 'Firecracker preflight ready=true (host appears capable for snapshot/vsock runtime).'
    } else {
        Write-Log 'Firecracker preflight ready=false (host prerequisites missing or snapshot paths not configured).'
    }
}
finally {
    Write-Log 'Restoring backend/worker defaults.'
    Clear-OverrideEnvs
    docker compose up -d --force-recreate backend worker-code-eval | Out-Null
    try {
        $finalStatus = Invoke-RestMethod -Method Get -Uri "$base/code-eval/runtime/status"
        Write-Log ("final_runtime_status=" + ($finalStatus | ConvertTo-Json -Depth 12 -Compress))
    } catch {
        Write-Log ("final_runtime_status_error=" + $_.Exception.Message)
    }
}

Write-Output "Preflight log written to $logPath"
