Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$base = 'http://localhost:8080/api/v1'
$ts = Get-Date -Format 'yyyyMMddHHmmss'
$logPath = "d:/dev/DEP/logs/code_eval_ai_shim_real_e2e_$ts.txt"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 's'), $Message
    Add-Content -Path $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

function Write-RawJson {
    param(
        [string]$Label,
        [string]$JsonText
    )
    Write-Log "$Label RAW-BEGIN"
    Add-Content -Path $logPath -Value $JsonText -Encoding UTF8
    Write-Log "$Label RAW-END"
}

function Invoke-JsonApi {
    param(
        [ValidateSet('GET', 'POST', 'PATCH')]
        [string]$Method,
        [string]$Url,
        $BodyObj = $null
    )

    $jsonBody = $null
    if ($null -ne $BodyObj) {
        $jsonBody = $BodyObj | ConvertTo-Json -Depth 20
        Write-RawJson "REQUEST $Method $Url" $jsonBody
    } else {
        Write-Log "REQUEST $Method $Url"
    }

    if ($null -ne $jsonBody) {
        $resp = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $Url -ContentType 'application/json' -Body $jsonBody
    } else {
        $resp = Invoke-WebRequest -UseBasicParsing -Method $Method -Uri $Url
    }

    $raw = [string]$resp.Content
    Write-RawJson "RESPONSE $Method $Url" $raw
    return $raw | ConvertFrom-Json
}

function New-Submission {
    param(
        [string]$AssignmentId,
        [string]$StudentId,
        [string]$StudentName,
        [string]$FileText
    )

    $tmpPath = "d:/dev/DEP/logs/ai_shim_upload_$StudentId.txt"
    Set-Content -Path $tmpPath -Value $FileText -Encoding UTF8

    $url = "$base/submissions/$AssignmentId/upload?student_id=$StudentId&student_name=$([uri]::EscapeDataString($StudentName))"
    Write-Log "REQUEST POST $url (multipart/form-data)"
    $raw = (& curl.exe -sS -X POST $url -F "file=@$tmpPath;type=text/plain")
    Write-RawJson "RESPONSE POST $url" $raw
    return $raw | ConvertFrom-Json
}

function Wait-ForJobTerminal {
    param([string]$JobId)

    $final = $null
    for ($i = 0; $i -lt 120; $i++) {
        $url = "$base/code-eval/jobs/$JobId"
        $raw = (& curl.exe -sS $url)
        $obj = $raw | ConvertFrom-Json
        Write-Log "POLL job=$JobId iteration=$i status=$($obj.status) attempts=$($obj.attempt_count)"
        if ($obj.status -in @('COMPLETED', 'FAILED')) {
            Write-RawJson "RESPONSE FINAL GET $url" $raw
            $final = $obj
            break
        }
        Start-Sleep -Seconds 1
    }

    if ($null -eq $final) {
        throw "Timed out waiting for terminal state for job $JobId"
    }

    return $final
}

function Wait-ForBackend {
    param([int]$MaxSeconds = 120)

    for ($i = 0; $i -lt $MaxSeconds; $i++) {
        try {
            $healthRaw = (& curl.exe -sS http://localhost:8080/health)
            if ($LASTEXITCODE -eq 0 -and $healthRaw) {
                $health = $healthRaw | ConvertFrom-Json
                if ($health.status -eq 'ok') {
                    Write-Log "Backend health ready after ${i}s"
                    return
                }
            }
        } catch {
            # ignore until timeout
        }
        Start-Sleep -Seconds 1
    }

    throw "Backend did not become healthy within ${MaxSeconds}s"
}

function Get-OptionalValue {
    param(
        $Object,
        [string]$Name
    )
    if ($null -eq $Object) {
        return $null
    }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) {
        return $null
    }
    return $prop.Value
}

"Code Eval AI Shim Real E2E`nDate: $(Get-Date -Format 'yyyy-MM-dd')`n" | Set-Content -Path $logPath -Encoding UTF8

Write-Log 'STEP 0: Wait for backend health'
Wait-ForBackend -MaxSeconds 180

Write-Log 'STEP 1: Runtime status precheck'
$runtime = Invoke-JsonApi -Method GET -Url "$base/code-eval/runtime/status"

Write-Log 'STEP 2: Create assignment'
$assignment = Invoke-JsonApi -Method POST -Url "$base/assignments/" -BodyObj @{
    course_id = "course-ai-shim-real-$ts"
    title = "AI Shim Real E2E $ts"
    description = 'real model ai shim end-to-end run'
    max_marks = 100
    question_type = 'subjective'
    has_code_question = $true
}

Write-Log 'STEP 3: Create ready environment version'
$envVersion = Invoke-JsonApi -Method POST -Url "$base/code-eval/environments/versions" -BodyObj @{
    course_id = $assignment.course_id
    assignment_id = $assignment.id
    profile_key = 'python-basic'
    reuse_mode = 'course_reuse_with_assignment_overrides'
    spec_json = @{ mode = 'manifest'; runtime = 'python-3.11' }
    freeze_key = "codeeval/ai-shim-real-$ts"
    status = 'ready'
    version_number = 1
    is_active = $true
    created_by = 'ai-shim-real-e2e-script'
}

$scenarios = @(
    @{
        name = 'fixable_interface_mismatch_argv_vs_stdin'
        source = "import sys`nif len(sys.argv) > 1:`n    print(sys.argv[1])`nelse:`n    print('')"
        testcases = @(
            @{
                testcase_id = 'tc1'
                weight = 1.0
                input_mode = 'stdin'
                stdin = '2'
                expected_stdout = "2`n"
                expected_stderr = ''
                expected_exit_code = 0
            },
            @{
                testcase_id = 'tc2'
                weight = 1.0
                input_mode = 'stdin'
                stdin = '7'
                expected_stdout = "7`n"
                expected_stderr = ''
                expected_exit_code = 0
            }
        )
    },
    @{
        name = 'logic_bug_candidate'
        source = "import sys`nprint(int(sys.stdin.read().strip()) + 1)"
        testcases = @(
            @{
                testcase_id = 'tc1'
                weight = 1.0
                input_mode = 'stdin'
                stdin = '2'
                expected_stdout = '999'
                expected_stderr = ''
                expected_exit_code = 0
            }
        )
    }
)

$results = @()

for ($idx = 0; $idx -lt $scenarios.Count; $idx++) {
    $scenario = $scenarios[$idx]
    Write-Log "STEP 4.$($idx+1): Scenario=$($scenario.name) upload submission"
    $upload = New-Submission -AssignmentId $assignment.id -StudentId "stu-$($idx+1)-$ts" -StudentName "Shim Scenario $($idx+1)" -FileText "placeholder-$($scenario.name)-$ts"
    $submissionId = Get-OptionalValue -Object $upload -Name 'submission_id'
    if (-not $submissionId) {
        throw "Upload did not return submission_id for scenario '$($scenario.name)'."
    }

    Write-Log "STEP 5.$($idx+1): Create code-eval job for scenario=$($scenario.name)"
    $job = Invoke-JsonApi -Method POST -Url "$base/code-eval/jobs" -BodyObj @{
        environment_version_id = $envVersion.id
        explicit_regrade = $true
        request = @{
            assignment_id = $assignment.id
            submission_id = $submissionId
            language = 'python'
            entrypoint = 'main.py'
            source_files = @{ 'main.py' = $scenario.source }
            testcases = $scenario.testcases
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
    }

    Write-Log "STEP 6.$($idx+1): Poll job to terminal"
    $final = Wait-ForJobTerminal -JobId $job.id

    $finalResult = if ($null -ne $final.final_result_json) { $final.final_result_json } else { @{} }
    $shimDecision = if ($null -ne $finalResult.shim_decision) { $finalResult.shim_decision } else { @{} }
    $nestedAiDecision = Get-OptionalValue -Object $shimDecision -Name 'ai_decision'
    $shimModel = Get-OptionalValue -Object $shimDecision -Name 'model'
    if (-not $shimModel) {
        $shimModel = Get-OptionalValue -Object $nestedAiDecision -Name 'model'
    }

    $promptHash = Get-OptionalValue -Object $shimDecision -Name 'prompt_hash'
    if (-not $promptHash) {
        $promptHash = Get-OptionalValue -Object $nestedAiDecision -Name 'prompt_hash'
    }

    $results += [pscustomobject]@{
        scenario = $scenario.name
        job_id = $job.id
        status = $final.status
        attempt_count = $final.attempt_count
        shim_eligible = Get-OptionalValue -Object $shimDecision -Name 'eligible'
        shim_strategy = Get-OptionalValue -Object $shimDecision -Name 'shim_strategy'
        shim_reason = Get-OptionalValue -Object $shimDecision -Name 'reason'
        shim_model = $shimModel
        has_prompt_hash = [bool]$promptHash
    }
}

Write-Log 'STEP 7: Summary'
$summary = $results | ConvertTo-Json -Depth 8
Write-RawJson 'SUMMARY' $summary
Write-Output "AI shim real e2e log written to $logPath"