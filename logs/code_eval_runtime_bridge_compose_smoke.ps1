$ErrorActionPreference = 'Stop'

$repoRoot = 'd:/dev/DEP'
$base = 'http://localhost:8080/api/v1'
$date = Get-Date -Format 'yyyy-MM-dd'
$logPath = "d:/dev/DEP/logs/code_eval_runtime_bridge_compose_smoke_$date.txt"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 's'), $Message
    Add-Content -Path $logPath -Value $line -Encoding UTF8
    Write-Output $line
}

function Wait-Http {
    param(
        [string]$Url,
        [int]$MaxAttempts = 40,
        [int]$SleepSeconds = 2
    )

    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        try {
            $response = Invoke-RestMethod -Method Get -Uri $Url
            return $response
        } catch {
            Start-Sleep -Seconds $SleepSeconds
        }
    }

    throw "Timed out waiting for URL: $Url"
}

function Wait-CodeEvalJobTerminal {
    param(
        [string]$JobId,
        [int]$MaxAttempts = 50,
        [int]$SleepSeconds = 2
    )

    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        Start-Sleep -Seconds $SleepSeconds
        $job = Invoke-RestMethod -Method Get -Uri "$base/code-eval/jobs/$JobId"
        if ($job.status -in @('COMPLETED', 'FAILED')) {
            return $job
        }
    }

    throw "Timed out waiting for code-eval job terminal state: $JobId"
}

function New-CodeEvalSmokeContext {
    $suffix = Get-Date -Format 'yyyyMMddHHmmss'

    $assignmentBody = @{
        course_id = "course-runtime-bridge-smoke-$suffix"
        title = "Runtime Bridge Compose Smoke $suffix"
        description = "Automated runtime bridge compose smoke"
        max_marks = 100
        question_type = 'subjective'
        has_code_question = $true
    } | ConvertTo-Json

    $assignment = Invoke-RestMethod -Method Post -Uri "$base/assignments/" -ContentType 'application/json' -Body $assignmentBody

    $envBody = @{
        course_id = $assignment.course_id
        assignment_id = $assignment.id
        profile_key = 'python-basic'
        reuse_mode = 'course_reuse_with_assignment_overrides'
        spec_json = @{
            mode = 'manifest'
            runtime = 'python-3.11'
            manifest = @{ 'python' = '3.11.9' }
        }
        freeze_key = "bridge-smoke-$suffix"
        status = 'ready'
        version_number = 1
        is_active = $true
        created_by = 'runtime-bridge-smoke-script'
    } | ConvertTo-Json -Depth 10

    $envVersion = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions" -ContentType 'application/json' -Body $envBody

    $uploadPath = "d:/dev/DEP/logs/runtime_bridge_smoke_upload_$suffix.txt"
    "print('bridge-smoke')" | Set-Content -Path $uploadPath -Encoding UTF8
    $uploadRaw = & curl.exe -sS -X POST "$base/submissions/$($assignment.id)/upload?student_id=student-bridge-$suffix&student_name=Runtime%20Bridge" -F "file=@$uploadPath;type=text/plain"
    $upload = $uploadRaw | ConvertFrom-Json

    return [ordered]@{
        assignment_id = $assignment.id
        submission_id = $upload.submission_id
        environment_version_id = $envVersion.id
        course_id = $assignment.course_id
    }
}

function New-JobBody {
    param(
        [hashtable]$Context,
        [string]$SourceCode,
        [array]$Testcases
    )

    return @{
        environment_version_id = $Context.environment_version_id
        explicit_regrade = $true
        request = @{
            assignment_id = $Context.assignment_id
            submission_id = $Context.submission_id
            language = 'python'
            entrypoint = 'solution.py'
            source_files = @{ 'solution.py' = $SourceCode }
            testcases = $Testcases
            environment = @{
                mode = 'manifest'
                reuse_mode = 'course_reuse_with_assignment_overrides'
                runtime = 'python-3.11'
                clean_strategy = 'ephemeral_clone'
            }
            quality_evaluation = @{
                mandatory_per_assignment = $true
                mode = 'disabled'
                rubric_source_mode = 'instructor_provided'
                weight_percent = 0.0
                dimensions = @('readability')
            }
            regrade_policy = 'force_reprocess_all'
            quota = @{
                timeout_seconds = 5.0
                memory_mb = 256
                max_output_kb = 256
                network_enabled = $false
            }
        }
    } | ConvertTo-Json -Depth 20
}

function Clear-OverrideEnvs {
    $names = @(
        'CODE_EVAL_EXECUTION_BACKEND',
        'CODE_EVAL_MICROVM_ENABLE_ADAPTER',
        'CODE_EVAL_MICROVM_RUNTIME_MODE',
        'CODE_EVAL_MICROVM_ALLOW_FALLBACK',
        'CODE_EVAL_MICROVM_RUNTIME_BRIDGE_URL',
        'CODE_EVAL_MICROVM_RUNTIME_BRIDGE_API_KEY',
        'RUNTIME_BRIDGE_EXECUTOR_MODE',
        'RUNTIME_BRIDGE_MICROVM_EXECUTE_URL',
        'RUNTIME_BRIDGE_MICROVM_API_KEY',
        'RUNTIME_BRIDGE_MICROVM_TIMEOUT_SECONDS',
        'RUNTIME_BRIDGE_MICROVM_VERIFY_TLS'
    )
    foreach ($name in $names) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
}

Set-Location $repoRoot
"Code Eval Runtime Bridge Compose Smoke`nDate: $date`n" | Set-Content -Path $logPath -Encoding UTF8

try {
    Write-Log 'Scenario A: local_reference bridge mode success'
    $env:CODE_EVAL_MICROVM_RUNTIME_BRIDGE_API_KEY = 'bridge-secret'
    $env:CODE_EVAL_EXECUTION_BACKEND = 'microvm'
    $env:CODE_EVAL_MICROVM_ENABLE_ADAPTER = 'true'
    $env:CODE_EVAL_MICROVM_RUNTIME_MODE = 'runtime_bridge'
    $env:CODE_EVAL_MICROVM_ALLOW_FALLBACK = 'false'
    $env:CODE_EVAL_MICROVM_RUNTIME_BRIDGE_URL = 'http://runtime-bridge:8099/execute'
    $env:RUNTIME_BRIDGE_EXECUTOR_MODE = 'local_reference'

    docker compose up -d --build --force-recreate runtime-bridge backend worker-code-eval | Out-Null

    Wait-Http -Url 'http://localhost:8080/health' | Out-Null
    Wait-Http -Url 'http://localhost:8099/health' | Out-Null

    $runtimeStatus = Invoke-RestMethod -Method Get -Uri 'http://localhost:8080/api/v1/code-eval/runtime/status'
    $bridgeStatus = Invoke-RestMethod -Method Get -Uri 'http://localhost:8099/runtime/status'
    Write-Log ("runtime_status=" + ($runtimeStatus | ConvertTo-Json -Depth 8 -Compress))
    Write-Log ("bridge_status=" + ($bridgeStatus | ConvertTo-Json -Depth 8 -Compress))

    $ctxSuccess = New-CodeEvalSmokeContext
    Write-Log ("smoke_context_success=" + ($ctxSuccess | ConvertTo-Json -Compress))

    $jobBodySuccess = New-JobBody -Context $ctxSuccess -SourceCode "import sys`nnums=[int(x) for x in sys.stdin.read().split() if x]`nprint(sum(nums))" -Testcases @(
        @{ testcase_id = 'tc1'; weight = 1.0; input_mode = 'stdin'; stdin = '1 2 3'; expected_stdout = '6'; expected_stderr = ''; expected_exit_code = 0 },
        @{ testcase_id = 'tc2'; weight = 1.0; input_mode = 'stdin'; stdin = '4 6'; expected_stdout = '10'; expected_stderr = ''; expected_exit_code = 0 }
    )

    $createdSuccess = Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $jobBodySuccess
    $finalSuccess = Wait-CodeEvalJobTerminal -JobId $createdSuccess.id
    Write-Log ("job_success_id=$($createdSuccess.id) status=$($finalSuccess.status) score=$($finalSuccess.final_result_json.total_score)")

    Write-Log 'Scenario B: auth mismatch failure (backend key != bridge key)'
    $env:CODE_EVAL_MICROVM_RUNTIME_BRIDGE_API_KEY = 'wrong-secret'
    docker compose up -d --force-recreate backend worker-code-eval | Out-Null

    Wait-Http -Url 'http://localhost:8080/health' | Out-Null

    $ctxFail = New-CodeEvalSmokeContext
    Write-Log ("smoke_context_failure=" + ($ctxFail | ConvertTo-Json -Compress))

    $jobBodyFail = New-JobBody -Context $ctxFail -SourceCode "print('x')" -Testcases @(
        @{ testcase_id = 'tc1'; weight = 1.0; input_mode = 'stdin'; stdin = ''; expected_stdout = 'x'; expected_stderr = ''; expected_exit_code = 0 }
    )

    $createdFail = Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $jobBodyFail
    $finalFail = Wait-CodeEvalJobTerminal -JobId $createdFail.id
    $failErr = [string]$finalFail.error_message
    Write-Log ("job_failure_id=$($createdFail.id) status=$($finalFail.status) error=$failErr")

    if ($finalFail.status -ne 'FAILED' -or $failErr -notmatch '401') {
        throw 'Auth mismatch scenario did not fail with expected runtime bridge 401 behavior.'
    }

    Write-Log 'Scenario C: smoke complete'
} finally {
    Write-Log 'Restoring compose defaults (runtime-bridge, backend, worker-code-eval)'
    Clear-OverrideEnvs
    docker compose up -d --force-recreate runtime-bridge backend worker-code-eval | Out-Null
    try {
        Wait-Http -Url 'http://localhost:8080/health' | Out-Null
        $finalRuntime = Invoke-RestMethod -Method Get -Uri 'http://localhost:8080/api/v1/code-eval/runtime/status'
        Write-Log ("final_runtime_status=" + ($finalRuntime | ConvertTo-Json -Depth 8 -Compress))
    } catch {
        Write-Log ("final_runtime_status_error=" + $_.Exception.Message)
    }
}

Write-Output "Smoke log written to $logPath"
