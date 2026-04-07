param(
    [switch]$ForceRefreshSnapshot,
    [switch]$SkipSnapshotProbe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$rootDir = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
Set-Location $rootDir

function Invoke-RestWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [string]$ContentType,
        [string]$Body,
        [int]$MaxAttempts = 6
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            if ($PSBoundParameters.ContainsKey('Body') -and $Body) {
                return Invoke-RestMethod -Method $Method -Uri $Uri -DisableKeepAlive -ContentType $ContentType -Body $Body
            }
            return Invoke-RestMethod -Method $Method -Uri $Uri -DisableKeepAlive
        } catch {
            if ($attempt -eq $MaxAttempts) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

Write-Host "[firecracker-smoke] starting backend/worker stack..."
& docker compose -f docker-compose.yml -f docker-compose.microvm.yml up -d postgres redis backend worker-code-eval

$snapshotVmstate = Join-Path $rootDir "microvm/snapshots/python311.vmstate"
$snapshotMem = Join-Path $rootDir "microvm/snapshots/python311.mem"
$needSnapshot = $ForceRefreshSnapshot.IsPresent -or -not (Test-Path $snapshotVmstate) -or -not (Test-Path $snapshotMem)

if ($needSnapshot) {
    Write-Host "[firecracker-smoke] creating snapshot artifacts..."
    & docker compose cp microvm/scripts/create_snapshot_with_guest_agent.sh backend:/tmp/create_snapshot_with_guest_agent.sh | Out-Null
    & docker compose cp microvm/scripts/vsock_frame_client.py backend:/tmp/vsock_frame_client.py | Out-Null

    $skipProbe = if ($SkipSnapshotProbe.IsPresent) { "true" } else { "false" }
    $snapshotCmd = "set -euo pipefail; chmod +x /tmp/create_snapshot_with_guest_agent.sh; SKIP_GUEST_PROBE=${skipProbe} FIRECRACKER_BIN=/usr/local/bin/firecracker KERNEL_IMAGE=/opt/microvm/assets/vmlinux.bin ROOTFS_IMAGE=/opt/microvm/assets/python311-agent.rootfs.ext4 SNAPSHOT_DIR=/opt/microvm/snapshots SNAPSHOT_NAME=python311 /tmp/create_snapshot_with_guest_agent.sh"
    & docker compose exec backend /bin/bash -lc $snapshotCmd
} else {
    Write-Host "[firecracker-smoke] reusing existing snapshot artifacts."
}

$preflight = Invoke-RestWithRetry -Method Get -Uri "http://localhost:8080/api/v1/code-eval/runtime/preflight"
if (-not $preflight.firecracker.ready) {
    $payload = $preflight | ConvertTo-Json -Depth 12
    throw "Firecracker preflight not ready:`n$payload"
}

$base = "http://localhost:8080/api/v1"
$suffix = Get-Date -Format 'yyyyMMddHHmmss'

$assignmentBody = @{
    course_id = "course-firecracker-live-$suffix"
    title = "Firecracker Live $suffix"
    description = "firecracker e2e validation"
    max_marks = 100
    question_type = "subjective"
    has_code_question = $true
} | ConvertTo-Json -Depth 6
$assignment = Invoke-RestWithRetry -Method Post -Uri "$base/assignments/" -ContentType 'application/json' -Body $assignmentBody

$envBody = @{
    course_id = $assignment.course_id
    assignment_id = $assignment.id
    profile_key = "python-basic"
    reuse_mode = "course_reuse_with_assignment_overrides"
    spec_json = @{
        mode = "manifest"
        runtime = "python-3.11"
        manifest = @{ python = "3.11.9" }
    }
    freeze_key = "firecracker-live-$suffix"
    status = "ready"
    version_number = 1
    is_active = $true
    created_by = "firecracker-smoke-ps1"
} | ConvertTo-Json -Depth 8
$envVersion = Invoke-RestWithRetry -Method Post -Uri "$base/code-eval/environments/versions" -ContentType 'application/json' -Body $envBody

New-Item -ItemType Directory -Force -Path (Join-Path $rootDir "logs") | Out-Null
$uploadFile = Join-Path $rootDir "logs/firecracker_smoke_upload_$suffix.txt"
Set-Content -Path $uploadFile -Value "print('upload')" -Encoding UTF8

$uploadUri = "$base/submissions/$($assignment.id)/upload?student_id=student-firecracker-$suffix&student_name=FirecrackerSmoke"
$uploadJson = & curl.exe -sS -X POST $uploadUri -F "file=@$uploadFile;type=text/plain"
$upload = $uploadJson | ConvertFrom-Json

$jobBody = @{
    environment_version_id = $envVersion.id
    explicit_regrade = $true
    request = @{
        assignment_id = $assignment.id
        submission_id = $upload.submission_id
        language = "python"
        entrypoint = "solution.py"
        source_files = @{
            "solution.py" = "import sys`nnums=[int(x) for x in sys.stdin.read().split() if x]`nprint(sum(nums))"
        }
        testcases = @(
            @{
                testcase_id = "tc1"
                weight = 1.0
                input_mode = "stdin"
                stdin = "1 2 3"
                expected_stdout = "6"
                expected_stderr = ""
                expected_exit_code = 0
            },
            @{
                testcase_id = "tc2"
                weight = 1.0
                input_mode = "stdin"
                stdin = "4 5"
                expected_stdout = "9"
                expected_stderr = ""
                expected_exit_code = 0
            }
        )
        environment = @{
            mode = "manifest"
            reuse_mode = "course_reuse_with_assignment_overrides"
            runtime = "python-3.11"
            clean_strategy = "ephemeral_clone"
        }
        quality_evaluation = @{
            mandatory_per_assignment = $true
            mode = "disabled"
            rubric_source_mode = "instructor_provided"
            weight_percent = 0.0
            dimensions = @("readability")
        }
        regrade_policy = "force_reprocess_all"
        quota = @{
            timeout_seconds = 5.0
            memory_mb = 256
            max_output_kb = 256
            network_enabled = $false
        }
    }
} | ConvertTo-Json -Depth 14

$job = Invoke-RestWithRetry -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $jobBody

$detail = $null
for ($i = 0; $i -lt 120; $i++) {
    $detail = Invoke-RestWithRetry -Method Get -Uri "$base/code-eval/jobs/$($job.id)"
    if ($detail.status -eq "COMPLETED" -or $detail.status -eq "FAILED") {
        break
    }
    Start-Sleep -Seconds 2
}

$result = [pscustomobject]@{
    assignment_id = $assignment.id
    environment_version_id = $envVersion.id
    submission_id = $upload.submission_id
    job_id = $job.id
    status = $detail.status
    error_message = $detail.error_message
    final_result = $detail.final_result_json
}

$result | ConvertTo-Json -Depth 18

if ($detail.status -ne "COMPLETED") {
    throw "Firecracker smoke failed. job_id=$($job.id) status=$($detail.status)"
}
