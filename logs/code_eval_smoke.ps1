$ErrorActionPreference = 'Stop'
$base='http://localhost:8080/api/v1'

$assignmentBody = @{ course_id='course-codeeval-smoke'; title='Code Eval Smoke Assignment'; description='Phase1 API smoke'; max_marks=100; question_type='subjective'; has_code_question=$true } | ConvertTo-Json
$assignment = Invoke-RestMethod -Method Post -Uri "$base/assignments/" -ContentType 'application/json' -Body $assignmentBody
Write-Output ("assignment_id=" + $assignment.id)

$envBody = @{ course_id=$assignment.course_id; assignment_id=$assignment.id; profile_key='python-basic'; reuse_mode='course_reuse_with_assignment_overrides'; spec_json=@{ mode='manifest'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9'; 'pip:pytest'='8.3.5' } }; status='ready'; version_number=1; is_active=$true; created_by='smoke-script' } | ConvertTo-Json -Depth 10
$envVersion = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions" -ContentType 'application/json' -Body $envBody
Write-Output ("environment_version_id=" + $envVersion.id)

$approvalSolutionBody = @{ assignment_id=$assignment.id; artifact_type='ai_solution'; version_number=1; content_json=@{ language='python'; solution='def solve(): pass' }; requested_by='smoke-script' } | ConvertTo-Json -Depth 10
$approvalSolution = Invoke-RestMethod -Method Post -Uri "$base/code-eval/approvals" -ContentType 'application/json' -Body $approvalSolutionBody
Write-Output ("approval_solution_id=" + $approvalSolution.id + " status=" + $approvalSolution.status)

$approvalTestsBody = @{ assignment_id=$assignment.id; artifact_type='ai_tests'; version_number=1; content_json=@{ tests=@(@{ name='happy_path'; input='hello'; expected='hello' }, @{ name='edge_case'; input=''; expected='' }, @{ name='invalid_input'; input='###'; expected='error' }) }; requested_by='smoke-script' } | ConvertTo-Json -Depth 12
$approvalTests = Invoke-RestMethod -Method Post -Uri "$base/code-eval/approvals" -ContentType 'application/json' -Body $approvalTestsBody
Write-Output ("approval_tests_id=" + $approvalTests.id + " status=" + $approvalTests.status)

$approveBody = @{ actor='instructor-smoke'; reason='Approved for smoke run' } | ConvertTo-Json
$approvalSolutionApproved = Invoke-RestMethod -Method Post -Uri "$base/code-eval/approvals/$($approvalSolution.id)/approve" -ContentType 'application/json' -Body $approveBody
$approvalTestsApproved = Invoke-RestMethod -Method Post -Uri "$base/code-eval/approvals/$($approvalTests.id)/approve" -ContentType 'application/json' -Body $approveBody
Write-Output ("approval_solution_status_after=" + $approvalSolutionApproved.status)
Write-Output ("approval_tests_status_after=" + $approvalTestsApproved.status)

$uploadPath = 'd:/dev/DEP/logs/code_eval_smoke_upload.txt'
"print('hello')" | Set-Content -Path $uploadPath -Encoding UTF8
$uploadRaw = & curl.exe -sS -X POST "$base/submissions/$($assignment.id)/upload?student_id=student-codeeval-1&student_name=CodeEval%20Student" -F "file=@$uploadPath;type=text/plain"
$upload = $uploadRaw | ConvertFrom-Json
Write-Output ("submission_id=" + $upload.submission_id)

$jobBody = @{
  environment_version_id = $envVersion.id
  explicit_regrade = $false
  request = @{
    assignment_id = $assignment.id
    submission_id = $upload.submission_id
    language = 'python'
    entrypoint = 'main.py'
    source_files = @{ 'main.py' = "print(input().strip())" }
    testcases = @(
      @{ testcase_id='t1'; weight=1.0; input_mode='stdin'; stdin='hello'; expected_stdout='hello'; expected_stderr=''; expected_exit_code=0 },
      @{ testcase_id='t2'; weight=1.0; input_mode='stdin'; stdin=''; expected_stdout=''; expected_stderr=''; expected_exit_code=0 }
    )
    environment = @{ mode='manifest'; reuse_mode='course_reuse_with_assignment_overrides'; course_profile_key='python-basic'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9' }; assignment_overrides=@{}; clean_strategy='ephemeral_clone' }
    quality_evaluation = @{ mandatory_per_assignment=$true; mode='rubric_only'; rubric_source_mode='instructor_provided'; weight_percent=20.0; rubric='Readability and structure'; dimensions=@('readability','structure'); model_name='gemini-2.5-flash' }
    regrade_policy = 'new_only_unless_explicit'
    quota = @{ timeout_seconds=5.0; memory_mb=256; max_output_kb=256; network_enabled=$false }
  }
} | ConvertTo-Json -Depth 25
$job = Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $jobBody
Write-Output ("job_id=" + $job.id + " initial_status=" + $job.status)

$jobDetail = Invoke-RestMethod -Method Get -Uri "$base/code-eval/jobs/$($job.id)"
Write-Output ("job_status_now=" + $jobDetail.status + " attempts=" + $jobDetail.attempts.Count)
