$ErrorActionPreference = 'Stop'
$base='http://localhost:8080/api/v1'
$assignmentId='a43c5d13-cc2c-4604-99c9-9a1302275f63'
$envVersionId='2665bab0-ba37-4cc7-b5cd-6445d7549940'
$subPass='da8b76ad-b95b-4569-894e-2b54150d84d5'
$subFail='dbb2cb0b-8096-4b03-bd4f-54b48747a2cc'

$jobBodyPass = @{
  environment_version_id = $envVersionId
  explicit_regrade = $true
  request = @{
    assignment_id = $assignmentId
    submission_id = $subPass
    language = 'python'
    entrypoint = 'main.py'
    source_files = @{ 'main.py' = "import sys`nprint(sys.stdin.read().strip())" }
    testcases = @(
      @{ testcase_id='t1'; weight=1.0; input_mode='stdin'; stdin='hello'; expected_stdout='hello'; expected_stderr=''; expected_exit_code=0 },
      @{ testcase_id='t2'; weight=1.0; input_mode='stdin'; stdin='world'; expected_stdout='world'; expected_stderr=''; expected_exit_code=0 }
    )
    environment = @{ mode='image_reference'; reuse_mode='course_reuse_with_assignment_overrides'; image_reference='python:3.11-slim'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9' }; assignment_overrides=@{}; clean_strategy='ephemeral_clone' }
    quality_evaluation = @{ mandatory_per_assignment=$true; mode='rubric_only'; rubric_source_mode='instructor_provided'; weight_percent=20.0; rubric='Style'; dimensions=@('readability','structure'); model_name='gemini-2.5-flash' }
    regrade_policy = 'new_only_unless_explicit'
    quota = @{ timeout_seconds=20.0; memory_mb=256; max_output_kb=256; network_enabled=$false }
  }
} | ConvertTo-Json -Depth 25
$jobPass = Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $jobBodyPass
Write-Output ("docker_job_pass_id=" + $jobPass.id + " initial_status=" + $jobPass.status)

$jobBodyFail = @{
  environment_version_id = $envVersionId
  explicit_regrade = $true
  request = @{
    assignment_id = $assignmentId
    submission_id = $subFail
    language = 'python'
    entrypoint = 'main.py'
    source_files = @{ 'main.py' = "print('wrong-output')" }
    testcases = @(
      @{ testcase_id='t1'; weight=1.0; input_mode='stdin'; stdin='hello'; expected_stdout='hello'; expected_stderr=''; expected_exit_code=0 },
      @{ testcase_id='t2'; weight=1.0; input_mode='stdin'; stdin='world'; expected_stdout='world'; expected_stderr=''; expected_exit_code=0 }
    )
    environment = @{ mode='image_reference'; reuse_mode='course_reuse_with_assignment_overrides'; image_reference='python:3.11-slim'; runtime='python-3.11'; manifest=@{ 'python'='3.11.9' }; assignment_overrides=@{}; clean_strategy='ephemeral_clone' }
    quality_evaluation = @{ mandatory_per_assignment=$true; mode='rubric_only'; rubric_source_mode='instructor_provided'; weight_percent=20.0; rubric='Style'; dimensions=@('readability','structure'); model_name='gemini-2.5-flash' }
    regrade_policy = 'new_only_unless_explicit'
    quota = @{ timeout_seconds=20.0; memory_mb=256; max_output_kb=256; network_enabled=$false }
  }
} | ConvertTo-Json -Depth 25
$jobFail = Invoke-RestMethod -Method Post -Uri "$base/code-eval/jobs" -ContentType 'application/json' -Body $jobBodyFail
Write-Output ("docker_job_fail_id=" + $jobFail.id + " initial_status=" + $jobFail.status)
