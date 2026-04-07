$ErrorActionPreference = 'Stop'
$base='http://localhost:8080/api/v1'

$assignmentBody = @{ course_id='course-build-hooks-20260407'; title='Env Build Hooks Smoke'; description='Validate build/freeze orchestration endpoints'; max_marks=100; question_type='subjective'; has_code_question=$true } | ConvertTo-Json
$assignment = Invoke-RestMethod -Method Post -Uri "$base/assignments/" -ContentType 'application/json' -Body $assignmentBody
Write-Output ("assignment_id=" + $assignment.id)

$envCreateBody = @{ course_id=$assignment.course_id; assignment_id=$assignment.id; profile_key='python-basic'; reuse_mode='course_reuse_with_assignment_overrides'; spec_json=@{ mode='manifest'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9'; 'pip:pytest'='8.3.5' } }; version_number=1; is_active=$true; created_by='smoke-2026-04-07' } | ConvertTo-Json -Depth 12
$envVersion = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions" -ContentType 'application/json' -Body $envCreateBody
Write-Output ("environment_version_id=" + $envVersion.id + " initial_status=" + $envVersion.status)

$publishPre = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions/$($envVersion.id)/validate-publish"
Write-Output ("publish_ready_before_build=" + $publishPre.ready_for_publish)
Write-Output ("publish_missing_before_build=" + ($publishPre.missing -join ','))

$uploadPath = 'd:/dev/DEP/logs/code_eval_env_build_upload.txt'
"print('build-hooks')" | Set-Content -Path $uploadPath -Encoding UTF8
$uploadRaw = & curl.exe -sS -X POST "$base/submissions/$($assignment.id)/upload?student_id=student-build-hooks&student_name=Build%20Hooks" -F "file=@$uploadPath;type=text/plain"
$upload = $uploadRaw | ConvertFrom-Json
Write-Output ("submission_id=" + $upload.submission_id)

$jobBodyBefore = @{
  environment_version_id = $envVersion.id
  explicit_regrade = $false
  request = @{
    assignment_id = $assignment.id
    submission_id = $upload.submission_id
    language = 'python'
    entrypoint = 'main.py'
    source_files = @{ 'main.py' = "print(input().strip())" }
    testcases = @(@{ testcase_id='t1'; weight=1.0; input_mode='stdin'; stdin='x'; expected_stdout='x'; expected_stderr=''; expected_exit_code=0 })
    environment = @{ mode='manifest'; reuse_mode='course_reuse_with_assignment_overrides'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9' }; assignment_overrides=@{}; clean_strategy='ephemeral_clone' }
    quality_evaluation = @{ mandatory_per_assignment=$true; mode='rubric_only'; rubric_source_mode='instructor_provided'; weight_percent=20.0; rubric='Style'; dimensions=@('readability'); model_name='gemini-2.5-flash' }
    regrade_policy = 'new_only_unless_explicit'
    quota = @{ timeout_seconds=5.0; memory_mb=256; max_output_kb=256; network_enabled=$false }
  }
} | ConvertTo-Json -Depth 25
try {
  Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $jobBodyBefore | Out-Null
  Write-Output 'unexpected_job_create_before_build_success=true'
} catch {
  $resp = $_.Exception.Response
  if ($resp -ne $null) {
    Write-Output ("job_create_before_build_status=" + [int]$resp.StatusCode)
  } else {
    Write-Output $_.Exception.Message
  }
}

$buildBody = @{ triggered_by='smoke-2026-04-07'; force_rebuild=$false } | ConvertTo-Json
$buildResp = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions/$($envVersion.id)/build" -ContentType 'application/json' -Body $buildBody
Write-Output ("build_enqueue_status=" + $buildResp.status + " env_status=" + $buildResp.environment_version.status)

$publishPost = $null
for ($i = 1; $i -le 30; $i++) {
  $publishPost = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions/$($envVersion.id)/validate-publish"
  if ($publishPost.ready_for_publish) { break }
}
Write-Output ("publish_ready_after_build=" + $publishPost.ready_for_publish)
Write-Output ("publish_missing_after_build=" + ($publishPost.missing -join ','))

$jobBodyAfter = @{
  environment_version_id = $envVersion.id
  explicit_regrade = $true
  request = @{
    assignment_id = $assignment.id
    submission_id = $upload.submission_id
    language = 'python'
    entrypoint = 'main.py'
    source_files = @{ 'main.py' = "print(input().strip())" }
    testcases = @(@{ testcase_id='t1'; weight=1.0; input_mode='stdin'; stdin='x'; expected_stdout='x'; expected_stderr=''; expected_exit_code=0 })
    environment = @{ mode='manifest'; reuse_mode='course_reuse_with_assignment_overrides'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9' }; assignment_overrides=@{}; clean_strategy='ephemeral_clone' }
    quality_evaluation = @{ mandatory_per_assignment=$true; mode='rubric_only'; rubric_source_mode='instructor_provided'; weight_percent=20.0; rubric='Style'; dimensions=@('readability'); model_name='gemini-2.5-flash' }
    regrade_policy = 'new_only_unless_explicit'
    quota = @{ timeout_seconds=5.0; memory_mb=256; max_output_kb=256; network_enabled=$false }
  }
} | ConvertTo-Json -Depth 25
$jobAfter = Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $jobBodyAfter
Write-Output ("job_id_after_build=" + $jobAfter.id + " initial_status=" + $jobAfter.status)
