Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$base = 'http://localhost:8080/api/v1'
$suffix = Get-Date -Format 'yyyyMMddHHmmss'

$assignmentBody = @{
    course_id = "course-static-$suffix"
    title = "Static Gate $suffix"
    description = 'static gate validation'
    max_marks = 100
    question_type = 'subjective'
    has_code_question = $true
} | ConvertTo-Json -Depth 6
$assignment = Invoke-RestMethod -Method Post -Uri "$base/assignments/" -ContentType 'application/json' -Body $assignmentBody

$envBody = @{
    course_id = $assignment.course_id
    assignment_id = $assignment.id
    profile_key = 'python-basic'
    reuse_mode = 'course_reuse_with_assignment_overrides'
    spec_json = @{ mode = 'manifest'; runtime = 'python-3.11' }
    freeze_key = "static-gate-$suffix"
    status = 'ready'
    version_number = 1
    is_active = $true
    created_by = 'static-gate-script'
} | ConvertTo-Json -Depth 8
$env = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions" -ContentType 'application/json' -Body $envBody

$uploadPath = "d:/dev/DEP/logs/static_gate_upload_$suffix.txt"
Set-Content -Path $uploadPath -Value "print('upload')" -Encoding UTF8
$uploadUri = "$base/submissions/$($assignment.id)/upload?student_id=student-$suffix&student_name=StaticGate"
$upload = (& curl.exe -sS -X POST $uploadUri -F "file=@$uploadPath;type=text/plain") | ConvertFrom-Json

$maliciousJobBody = @{
    environment_version_id = $env.id
    explicit_regrade = $true
    request = @{
        assignment_id = $assignment.id
        submission_id = $upload.submission_id
        language = 'python'
        entrypoint = 'main.py'
        source_files = @{ 'main.py' = "import os`nos.system('echo hi')`nprint(1)" }
        testcases = @(
            @{ testcase_id='tc1'; weight=1.0; input_mode='stdin'; stdin=''; expected_stdout='1'; expected_stderr=''; expected_exit_code=0 }
        )
        environment = @{ mode='manifest'; runtime='python-3.11' }
        quality_evaluation = @{ mandatory_per_assignment=$true; mode='disabled'; rubric_source_mode='instructor_provided'; weight_percent=0.0; dimensions=@('readability') }
        regrade_policy = 'force_reprocess_all'
        quota = @{ timeout_seconds=5.0; memory_mb=256; max_output_kb=256; network_enabled=$false }
    }
} | ConvertTo-Json -Depth 14
$maliciousJob = Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $maliciousJobBody

$detail = $null
for ($i=0; $i -lt 40; $i++) {
    $detail = Invoke-RestMethod -Method Get -Uri "$base/code-eval/jobs/$($maliciousJob.id)"
    if ($detail.status -in @('FAILED','COMPLETED')) { break }
    Start-Sleep -Seconds 1
}

$safeJobBody = @{
    environment_version_id = $env.id
    explicit_regrade = $true
    request = @{
        assignment_id = $assignment.id
        submission_id = $upload.submission_id
        language = 'python'
        entrypoint = 'main.py'
        source_files = @{ 'main.py' = "import sys`nprint(sum(int(x) for x in sys.stdin.read().split()))" }
        testcases = @(
            @{ testcase_id='tc1'; weight=1.0; input_mode='stdin'; stdin='1 2 3'; expected_stdout='6'; expected_stderr=''; expected_exit_code=0 }
        )
        environment = @{ mode='manifest'; runtime='python-3.11' }
        quality_evaluation = @{ mandatory_per_assignment=$true; mode='disabled'; rubric_source_mode='instructor_provided'; weight_percent=0.0; dimensions=@('readability') }
        regrade_policy = 'force_reprocess_all'
        quota = @{ timeout_seconds=5.0; memory_mb=256; max_output_kb=256; network_enabled=$false }
    }
} | ConvertTo-Json -Depth 14

$upload2Path = "d:/dev/DEP/logs/static_gate_upload2_$suffix.txt"
Set-Content -Path $upload2Path -Value "print('upload2')" -Encoding UTF8
$upload2 = (& curl.exe -sS -X POST "$base/submissions/$($assignment.id)/upload?student_id=student2-$suffix&student_name=Safe" -F "file=@$upload2Path;type=text/plain") | ConvertFrom-Json
$bodyObj = $safeJobBody | ConvertFrom-Json
$bodyObj.request.submission_id = $upload2.submission_id
$safeJobBody = $bodyObj | ConvertTo-Json -Depth 14
$safeJob = Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $safeJobBody

$safeDetail = $null
for ($i=0; $i -lt 60; $i++) {
    $safeDetail = Invoke-RestMethod -Method Get -Uri "$base/code-eval/jobs/$($safeJob.id)"
    if ($safeDetail.status -in @('FAILED','COMPLETED')) { break }
    Start-Sleep -Seconds 1
}

$result = [pscustomobject]@{
    static_job_id = $maliciousJob.id
    static_status = $detail.status
    static_error = $detail.error_message
    static_attempt_artifacts = if ($detail.attempts.Count -gt 0) { $detail.attempts[0].artifacts_json } else { $null }
    safe_job_id = $safeJob.id
    safe_status = $safeDetail.status
    safe_error = $safeDetail.error_message
    safe_final = $safeDetail.final_result_json
}

$result | ConvertTo-Json -Depth 20
