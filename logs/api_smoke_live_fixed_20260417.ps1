$ErrorActionPreference = "Stop"
$base = "http://localhost:8080"
$results = New-Object System.Collections.ArrayList

function Read-ResponseBody([System.Net.WebResponse]$resp) {
  if ($null -eq $resp) { return "" }
  try {
    $stream = $resp.GetResponseStream()
    if ($null -eq $stream) { return "" }
    $reader = New-Object System.IO.StreamReader($stream)
    $content = $reader.ReadToEnd()
    $reader.Close()
    return $content
  } catch {
    return ""
  }
}

function Add-Result($name, $ok, $code, $detail) {
  [void]$results.Add([pscustomobject]@{ name = $name; ok = $ok; status = $code; detail = $detail })
}

function Invoke-ApiJson {
  param(
    [string]$Name,
    [string]$Method,
    [string]$Url,
    [object]$BodyObj = $null,
    [int[]]$Allowed = @(200)
  )

  $bodyText = $null
  if ($null -ne $BodyObj) {
    $bodyText = $BodyObj | ConvertTo-Json -Depth 12
  }

  try {
    if ($null -ne $bodyText) {
      $resp = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $Url -ContentType "application/json" -Body $bodyText
    } else {
      $resp = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $Url
    }
    $code = [int]$resp.StatusCode
    $ok = $Allowed -contains $code
    Add-Result $Name $ok $code ($resp.Content.Substring(0, [Math]::Min(240, $resp.Content.Length)))
    return @{ code = $code; body = $resp.Content }
  } catch {
    $resp = $_.Exception.Response
    $code = if ($null -ne $resp) { [int]$resp.StatusCode } else { 0 }
    $text = Read-ResponseBody $resp
    $ok = $Allowed -contains $code
    Add-Result $Name $ok $code ($text.Substring(0, [Math]::Min(240, $text.Length)))
    return @{ code = $code; body = $text }
  }
}

# health
Invoke-ApiJson -Name "health" -Method "GET" -Url "$base/health" -Allowed @(200) | Out-Null

# assignment
$assignmentPayload = @{
  course_id = "SMOKE-COURSE-001"
  classroom_id = $null
  title = "Smoke Assignment"
  description = "Live API smoke"
  max_marks = 100
  question_type = "subjective"
  has_code_question = $false
}
$createAssignment = Invoke-ApiJson -Name "assignments.create" -Method "POST" -Url "$base/api/v1/assignments/" -BodyObj $assignmentPayload -Allowed @(201)
$assignment = if ($createAssignment.body) { $createAssignment.body | ConvertFrom-Json } else { $null }
$assignmentId = if ($null -ne $assignment) { $assignment.id } else { "" }

if (-not [string]::IsNullOrWhiteSpace($assignmentId)) {
  Invoke-ApiJson -Name "assignments.list" -Method "GET" -Url "$base/api/v1/assignments/" -Allowed @(200) | Out-Null
  Invoke-ApiJson -Name "assignments.get" -Method "GET" -Url "$base/api/v1/assignments/$assignmentId" -Allowed @(200) | Out-Null
  Invoke-ApiJson -Name "assignments.patch" -Method "PATCH" -Url "$base/api/v1/assignments/$assignmentId" -BodyObj @{ title = "Smoke Assignment Updated" } -Allowed @(200) | Out-Null
  Invoke-ApiJson -Name "assignments.validate" -Method "POST" -Url "$base/api/v1/assignments/$assignmentId/validate-publish" -BodyObj @{ environment_version_id = $null } -Allowed @(200) | Out-Null

  $rubricBody = @{
    source = "manual"
    content_json = @{
      questions = @(@{ id = "q1"; text = "sample"; max_marks = 100 })
      scoring_policy = @{}
    }
  }
  $rubricCreate = Invoke-ApiJson -Name "rubrics.create" -Method "POST" -Url "$base/api/v1/rubrics/$assignmentId" -BodyObj $rubricBody -Allowed @(201)
  $rubric = if ($rubricCreate.body) { $rubricCreate.body | ConvertFrom-Json } else { $null }
  $rubricId = if ($null -ne $rubric) { $rubric.id } else { "" }

  Invoke-ApiJson -Name "rubrics.list" -Method "GET" -Url "$base/api/v1/rubrics/$assignmentId" -Allowed @(200) | Out-Null

  if (-not [string]::IsNullOrWhiteSpace($rubricId)) {
    Invoke-ApiJson -Name "rubrics.approve" -Method "POST" -Url "$base/api/v1/rubrics/$rubricId/approve" -BodyObj @{ approved_by = "smoke" } -Allowed @(200) | Out-Null
  }

  Invoke-ApiJson -Name "assignments.publish" -Method "POST" -Url "$base/api/v1/assignments/$assignmentId/publish" -BodyObj @{ actor = "smoke"; force_republish = $true } -Allowed @(200,409) | Out-Null

  # submissions
  Invoke-ApiJson -Name "submissions.list.before" -Method "GET" -Url "$base/api/v1/submissions/$assignmentId" -Allowed @(200) | Out-Null

  $uploadFile = "d:\dev\DEP\logs\smoke_upload.txt"
  "smoke upload $(Get-Date -Format o)" | Out-File -FilePath $uploadFile -Encoding ascii -Force
  $uploadBodyFile = "d:\dev\DEP\logs\smoke_upload_response.json"
  $uploadCode = curl.exe -sS -o "$uploadBodyFile" -w "%{http_code}" -X POST "$base/api/v1/submissions/$assignmentId/upload?student_id=stu-smoke-1&student_name=Smoke+Student" -F "file=@$uploadFile"
  $uploadText = if (Test-Path $uploadBodyFile) { Get-Content $uploadBodyFile -Raw } else { "" }
  Add-Result "submissions.upload" ($uploadCode -eq "202") ([int]$uploadCode) ($uploadText.Substring(0, [Math]::Min(240, $uploadText.Length)))

  $subsResp = Invoke-ApiJson -Name "submissions.list.after" -Method "GET" -Url "$base/api/v1/submissions/$assignmentId" -Allowed @(200)
  $subs = if ($subsResp.body) { $subsResp.body | ConvertFrom-Json } else { @() }
  $submissionId = if ($subs.Count -gt 0) { $subs[0].id } else { "" }

  if (-not [string]::IsNullOrWhiteSpace($submissionId)) {
    Invoke-ApiJson -Name "submissions.detail" -Method "GET" -Url "$base/api/v1/submissions/detail/$submissionId" -Allowed @(200) | Out-Null
    Invoke-ApiJson -Name "submissions.grade" -Method "GET" -Url "$base/api/v1/submissions/$submissionId/grade" -Allowed @(200,404) | Out-Null
    Invoke-ApiJson -Name "submissions.audit" -Method "GET" -Url "$base/api/v1/submissions/$submissionId/audit" -Allowed @(200) | Out-Null
    Invoke-ApiJson -Name "submissions.ocr_correction" -Method "PATCH" -Url "$base/api/v1/submissions/$submissionId/ocr-correction" -BodyObj @{ block_index = 0; new_content = "x"; changed_by = "smoke" } -Allowed @(404,422) | Out-Null

    Invoke-ApiJson -Name "grades.push_draft" -Method "POST" -Url "$base/api/v1/grades/draft" -BodyObj @{ submission_ids = @($submissionId) } -Allowed @(202) | Out-Null
    Invoke-ApiJson -Name "grades.release" -Method "POST" -Url "$base/api/v1/grades/release" -BodyObj @{ submission_ids = @($submissionId) } -Allowed @(202) | Out-Null
  }

  # classroom
  Invoke-ApiJson -Name "classroom.auth_status" -Method "GET" -Url "$base/api/v1/classroom/auth-status" -Allowed @(200,503) | Out-Null
  Invoke-ApiJson -Name "classroom.status" -Method "GET" -Url "$base/api/v1/classroom/$assignmentId/status" -Allowed @(200) | Out-Null
  Invoke-ApiJson -Name "classroom.ingest" -Method "POST" -Url "$base/api/v1/classroom/$assignmentId/ingest" -BodyObj @{ course_id = "fake"; coursework_id = "fake"; force_reingest = $false } -Allowed @(200,422,503,500) | Out-Null
  Invoke-ApiJson -Name "classroom.sync_draft" -Method "POST" -Url "$base/api/v1/classroom/$assignmentId/sync-draft" -Allowed @(200,503,500) | Out-Null
  Invoke-ApiJson -Name "classroom.release" -Method "POST" -Url "$base/api/v1/classroom/$assignmentId/release" -Allowed @(200,503,500) | Out-Null

  # code-eval
  Invoke-ApiJson -Name "code_eval.runtime_status" -Method "GET" -Url "$base/api/v1/code-eval/runtime/status" -Allowed @(200) | Out-Null
  Invoke-ApiJson -Name "code_eval.runtime_preflight" -Method "GET" -Url "$base/api/v1/code-eval/runtime/preflight" -Allowed @(200) | Out-Null

  $codeAssignmentPayload = @{
    course_id = "SMOKE-COURSE-001"
    classroom_id = $null
    title = "Smoke Code Assignment"
    description = "Code eval smoke"
    max_marks = 100
    question_type = "subjective"
    has_code_question = $true
  }
  $codeAssignmentResp = Invoke-ApiJson -Name "assignments.create.code" -Method "POST" -Url "$base/api/v1/assignments/" -BodyObj $codeAssignmentPayload -Allowed @(201)
  $codeAssignment = if ($codeAssignmentResp.body) { $codeAssignmentResp.body | ConvertFrom-Json } else { $null }
  $codeAssignmentId = if ($null -ne $codeAssignment) { $codeAssignment.id } else { "" }

  if (-not [string]::IsNullOrWhiteSpace($codeAssignmentId)) {
    $envCreateBody = @{
      course_id = "SMOKE-COURSE-001"
      assignment_id = $codeAssignmentId
      profile_key = "python3.11-smoke"
      version_number = 1
      reuse_mode = "assignment_only"
      is_active = $true
      spec_json = @{
        language = "python"
        compile_flags = @()
        run_flags = @()
        timeout_seconds = 10
      }
    }
    $envCreate = Invoke-ApiJson -Name "code_eval.env.create" -Method "POST" -Url "$base/api/v1/code-eval/environments/versions" -BodyObj $envCreateBody -Allowed @(201)
    $env = if ($envCreate.body) { $envCreate.body | ConvertFrom-Json } else { $null }
    $envId = if ($null -ne $env) { $env.id } else { "" }

    Invoke-ApiJson -Name "code_eval.env.list" -Method "GET" -Url "$base/api/v1/code-eval/environments/versions" -Allowed @(200) | Out-Null

    if (-not [string]::IsNullOrWhiteSpace($envId)) {
      Invoke-ApiJson -Name "code_eval.env.get" -Method "GET" -Url "$base/api/v1/code-eval/environments/versions/$envId" -Allowed @(200) | Out-Null
      Invoke-ApiJson -Name "code_eval.env.validate_publish" -Method "POST" -Url "$base/api/v1/code-eval/environments/versions/$envId/validate-publish" -Allowed @(200) | Out-Null
      Invoke-ApiJson -Name "code_eval.env.build" -Method "POST" -Url "$base/api/v1/code-eval/environments/versions/$envId/build" -BodyObj @{ triggered_by = "smoke"; force_rebuild = $false } -Allowed @(200) | Out-Null
    }

    $approvalCreateBody = @{
      assignment_id = $codeAssignmentId
      artifact_type = "ai_tests"
      version_number = 1
      requested_by = "smoke"
      content_json = @{
        tests = @(
          @{ class = "happy_path" },
          @{ class = "edge_case" },
          @{ class = "invalid_input" }
        )
      }
    }
    $approvalCreate = Invoke-ApiJson -Name "code_eval.approvals.create" -Method "POST" -Url "$base/api/v1/code-eval/approvals" -BodyObj $approvalCreateBody -Allowed @(201)
    $approval = if ($approvalCreate.body) { $approvalCreate.body | ConvertFrom-Json } else { $null }
    $approvalId = if ($null -ne $approval) { $approval.id } else { "" }

    Invoke-ApiJson -Name "code_eval.approvals.list.with_assignment" -Method "GET" -Url "$base/api/v1/code-eval/approvals?assignment_id=$codeAssignmentId" -Allowed @(200) | Out-Null
    Invoke-ApiJson -Name "code_eval.approvals.list.without_assignment" -Method "GET" -Url "$base/api/v1/code-eval/approvals" -Allowed @(422) | Out-Null

    if (-not [string]::IsNullOrWhiteSpace($approvalId)) {
      Invoke-ApiJson -Name "code_eval.approvals.approve" -Method "POST" -Url "$base/api/v1/code-eval/approvals/$approvalId/approve" -BodyObj @{ actor = "smoke" } -Allowed @(200,422) | Out-Null
      Invoke-ApiJson -Name "code_eval.approvals.reject" -Method "POST" -Url "$base/api/v1/code-eval/approvals/$approvalId/reject" -BodyObj @{ actor = "smoke"; reason = "smoke reject" } -Allowed @(200) | Out-Null
      Invoke-ApiJson -Name "code_eval.approvals.generate_tests" -Method "POST" -Url "$base/api/v1/code-eval/approvals/$approvalId/generate-tests" -BodyObj @{ question_text = "print sum"; language = "python"; entrypoint = "main"; num_cases = 3; mode = "mode3" } -Allowed @(200,502,422) | Out-Null
    }

    Invoke-ApiJson -Name "code_eval.jobs.list" -Method "GET" -Url "$base/api/v1/code-eval/jobs" -Allowed @(200) | Out-Null
  }
}

$failures = $results | Where-Object { -not $_.ok }
"`n===== API SMOKE RESULTS ====="
$results | ForEach-Object { "[$($_.ok)] $($_.name) -> HTTP $($_.status)" }

if ($failures.Count -gt 0) {
  "`n===== FAILURES ====="
  $failures | ForEach-Object { "[$($_.name)] HTTP $($_.status) :: $($_.detail)" }
  exit 1
}

"`nAll smoke checks passed."
exit 0
