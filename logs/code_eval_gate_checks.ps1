$ErrorActionPreference = 'Stop'
$base='http://localhost:8080/api/v1'
Invoke-RestMethod -Method Get -Uri 'http://localhost:8080/health' | Out-Null

$assignmentBody = @{ course_id='course-codeeval-gates'; title='Code Eval Gate Check'; description='approval gate checks'; max_marks=100; question_type='subjective'; has_code_question=$true } | ConvertTo-Json
$assignment = Invoke-RestMethod -Method Post -Uri "$base/assignments/" -ContentType 'application/json' -Body $assignmentBody
Write-Output ("gate_assignment_id=" + $assignment.id)

$envBody = @{ course_id=$assignment.course_id; assignment_id=$assignment.id; profile_key='python-basic'; reuse_mode='course_reuse_with_assignment_overrides'; spec_json=@{ mode='manifest'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9' } }; status='ready'; version_number=1; is_active=$true; created_by='gate-smoke' } | ConvertTo-Json -Depth 10
$envVersion = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions" -ContentType 'application/json' -Body $envBody
Write-Output ("gate_env_version_id=" + $envVersion.id)

$approvalTestsBody = @{ assignment_id=$assignment.id; artifact_type='ai_tests'; version_number=1; content_json=@{ tests=@(@{ name='happy_path'; input='x'; expected='x' }) }; requested_by='gate-smoke' } | ConvertTo-Json -Depth 10
$approvalTests = Invoke-RestMethod -Method Post -Uri "$base/code-eval/approvals" -ContentType 'application/json' -Body $approvalTestsBody
Write-Output ("gate_ai_tests_approval_id=" + $approvalTests.id)

$approveBody = @{ actor='instructor-gate'; reason='approval gate test' } | ConvertTo-Json
try {
  Invoke-RestMethod -Method Post -Uri "$base/code-eval/approvals/$($approvalTests.id)/approve" -ContentType 'application/json' -Body $approveBody | Out-Null
  Write-Output 'unexpected_ai_tests_approve_success=true'
} catch {
  $resp = $_.Exception.Response
  if ($resp -ne $null) {
    Write-Output ("ai_tests_approve_status=" + [int]$resp.StatusCode)
  } else {
    Write-Output $_.Exception.Message
  }
}

$uploadPath = 'd:/dev/DEP/logs/code_eval_gate_upload.txt'
"print('gate')" | Set-Content -Path $uploadPath -Encoding UTF8
$uploadRaw = & curl.exe -sS -X POST "$base/submissions/$($assignment.id)/upload?student_id=student-gate-1&student_name=Gate%20Student" -F "file=@$uploadPath;type=text/plain"
$upload = $uploadRaw | ConvertFrom-Json
Write-Output ("gate_submission_id=" + $upload.submission_id)

$jobBody = @{
  environment_version_id = $envVersion.id
  explicit_regrade = $false
  request = @{
    assignment_id = $assignment.id
    submission_id = $upload.submission_id
    language = 'python'
    entrypoint = 'main.py'
    source_files = @{ 'main.py' = "print(input())" }
    testcases = @(@{ testcase_id='t1'; weight=1.0; input_mode='stdin'; stdin='x'; expected_stdout='x'; expected_stderr=''; expected_exit_code=0 })
    test_authoring = @{ mode='question_to_solution_and_tests'; question_text='Echo input' }
    environment = @{ mode='manifest'; reuse_mode='course_reuse_with_assignment_overrides'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9' }; assignment_overrides=@{}; clean_strategy='ephemeral_clone' }
    quality_evaluation = @{ mandatory_per_assignment=$true; mode='rubric_only'; rubric_source_mode='instructor_provided'; weight_percent=20.0; rubric='Style'; dimensions=@('readability'); model_name='gemini-2.5-flash' }
    regrade_policy = 'new_only_unless_explicit'
    quota = @{ timeout_seconds=5.0; memory_mb=256; max_output_kb=256; network_enabled=$false }
  }
} | ConvertTo-Json -Depth 25

try {
  Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $jobBody | Out-Null
  Write-Output 'unexpected_job_create_success=true'
} catch {
  $resp = $_.Exception.Response
  if ($resp -ne $null) {
    Write-Output ("job_create_status=" + [int]$resp.StatusCode)
  } else {
    Write-Output $_.Exception.Message
  }
}
