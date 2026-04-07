Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$base = 'http://localhost:8080/api/v1'
$suffix = Get-Date -Format 'yyyyMMddHHmmss'

$assignmentBody = @{
    course_id = "course-env-build-$suffix"
    title = "Env Build $suffix"
    description = 'env build api validation'
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
    spec_json = @{ mode = 'manifest'; runtime = 'python-3.11'; manifest = @{ python = '3.11.9' } }
    status = 'draft'
    version_number = 1
    is_active = $true
    created_by = 'env-build-api-script'
} | ConvertTo-Json -Depth 10
$env = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions" -ContentType 'application/json' -Body $envBody

$buildBody = @{ triggered_by = 'env-build-api-script'; force_rebuild = $false } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions/$($env.id)/build" -ContentType 'application/json' -Body $buildBody | Out-Null

$latest = $null
for ($i=0; $i -lt 40; $i++) {
    $items = Invoke-RestMethod -Method Get -Uri "$base/code-eval/environments/versions?assignment_id=$($assignment.id)"
    $latest = $items | Where-Object { $_.id -eq $env.id } | Select-Object -First 1
    if ($null -ne $latest -and ($latest.status -eq 'ready' -or $latest.status -eq 'failed')) { break }
    Start-Sleep -Seconds 1
}

$publishValidation = Invoke-RestMethod -Method Post -Uri "$base/code-eval/environments/versions/$($env.id)/validate-publish" -ContentType 'application/json' -Body '{}'

$result = [pscustomobject]@{
    environment_id = $env.id
    status = $latest.status
    freeze_key = $latest.freeze_key
    ready_for_publish = $publishValidation.ready_for_publish
    missing = $publishValidation.missing
}

$result | ConvertTo-Json -Depth 8
