$ErrorActionPreference = 'Stop'
$base='http://localhost:8080/api/v1'
Invoke-RestMethod -Method Get -Uri 'http://localhost:8080/health' | Out-Null

$assignmentBody = @{ course_id='course-codeeval-local-exec'; title='Code Eval Local Exec Smoke'; description='local executor smoke'; max_marks=100; question_type='subjective'; has_code_question=$true } | ConvertTo-Json
$assignment = Invoke-RestMethod -Method Post -Uri "$base/assignments/" -ContentType 'application/json' -Body $assignmentBody
Write-Output ("assignment_id=" + $assignment.id)

$envBody = @{ course_id=$assignment.course_id; assignment_id=$assignment.id; profile_key='python-basic'; reuse_mode='course_reuse_with_assignment_overrides'; spec_json=@{ mode='manifest'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9' } }; status='ready'; version_number=1; is_active=$true; created_by='local-exec-smoke' } | ConvertTo-Json -Depth 10
$envVersion = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions" -ContentType 'application/json' -Body $envBody
Write-Output ("environment_version_id=" + $envVersion.id)

$uploadPath1 = 'd:/dev/DEP/logs/code_eval_local_exec_upload_1.txt'
$uploadPath2 = 'd:/dev/DEP/logs/code_eval_local_exec_upload_2.txt'
"print('student1')" | Set-Content -Path $uploadPath1 -Encoding UTF8
"print('student2')" | Set-Content -Path $uploadPath2 -Encoding UTF8

$upload1Raw = & curl.exe -sS -X POST "$base/submissions/$($assignment.id)/upload?student_id=student-local-1&student_name=Local%20Student%201" -F "file=@$uploadPath1;type=text/plain"
$upload2Raw = & curl.exe -sS -X POST "$base/submissions/$($assignment.id)/upload?student_id=student-local-2&student_name=Local%20Student%202" -F "file=@$uploadPath2;type=text/plain"
$upload1 = $upload1Raw | ConvertFrom-Json
$upload2 = $upload2Raw | ConvertFrom-Json
Write-Output ("submission_1_id=" + $upload1.submission_id)
Write-Output ("submission_2_id=" + $upload2.submission_id)

$common = @{
  environment_version_id = $envVersion.id
  explicit_regrade = $false
}

$jobBodyPass = $common + @{
  request = @{
    assignment_id = $assignment.id
    submission_id = $upload1.submission_id
    language = 'python'
    entrypoint = 'main.py'
    source_files = @{ 'main.py' = "import sys`nprint(sys.stdin.read().strip())" }
    testcases = @(
      @{ testcase_id='t1'; weight=1.0; input_mode='stdin'; stdin='hello'; expected_stdout='hello'; expected_stderr=''; expected_exit_code=0 },
      @{ testcase_id='t2'; weight=1.0; input_mode='stdin'; stdin='world'; expected_stdout='world'; expected_stderr=''; expected_exit_code=0 }
    )
    environment = @{ mode='manifest'; reuse_mode='course_reuse_with_assignment_overrides'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9' }; assignment_overrides=@{}; clean_strategy='ephemeral_clone' }
    quality_evaluation = @{ mandatory_per_assignment=$true; mode='rubric_only'; rubric_source_mode='instructor_provided'; weight_percent=20.0; rubric='Style'; dimensions=@('readability','structure'); model_name='gemini-2.5-flash' }
    regrade_policy = 'new_only_unless_explicit'
    quota = @{ timeout_seconds=5.0; memory_mb=256; max_output_kb=256; network_enabled=$false }
  }
}
$jobPass = Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body ($jobBodyPass | ConvertTo-Json -Depth 25)
Write-Output ("job_pass_id=" + $jobPass.id + " initial_status=" + $jobPass.status)

$jobBodyFail = $common + @{
  request = @{
    assignment_id = $assignment.id
    submission_id = $upload2.submission_id
    language = 'python'
    entrypoint = 'main.py'
    source_files = @{ 'main.py' = "print('wrong-output')" }
    testcases = @(
      @{ testcase_id='t1'; weight=1.0; input_mode='stdin'; stdin='hello'; expected_stdout='hello'; expected_stderr=''; expected_exit_code=0 },
      @{ testcase_id='t2'; weight=1.0; input_mode='stdin'; stdin='world'; expected_stdout='world'; expected_stderr=''; expected_exit_code=0 }
    )
    environment = @{ mode='manifest'; reuse_mode='course_reuse_with_assignment_overrides'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9' }; assignment_overrides=@{}; clean_strategy='ephemeral_clone' }
    quality_evaluation = @{ mandatory_per_assignment=$true; mode='rubric_only'; rubric_source_mode='instructor_provided'; weight_percent=20.0; rubric='Style'; dimensions=@('readability','structure'); model_name='gemini-2.5-flash' }
    regrade_policy = 'new_only_unless_explicit'
    quota = @{ timeout_seconds=5.0; memory_mb=256; max_output_kb=256; network_enabled=$false }
  }
}
$jobFail = Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body ($jobBodyFail | ConvertTo-Json -Depth 25)
Write-Output ("job_fail_id=" + $jobFail.id + " initial_status=" + $jobFail.status)

$passDetail = Invoke-RestMethod -Method Get -Uri "$base/code-eval/jobs/$($jobPass.id)"
$failDetail = Invoke-RestMethod -Method Get -Uri "$base/code-eval/jobs/$($jobFail.id)"
Write-Output ("job_pass_status_now=" + $passDetail.status + " attempts=" + $passDetail.attempts.Count)
Write-Output ("job_fail_status_now=" + $failDetail.status + " attempts=" + $failDetail.attempts.Count)
