# AMGS Frontend — Full UI Specification

**For**: Frontend agent / developer  
**Backend base URL**: `http://localhost:8080` (dev) — all API calls use prefix `/api/v1`  
**Stack expectation**: Next.js (App Router) + TypeScript + Tailwind CSS. Dark-mode first.  
**Auth model (current)**: No user auth at the API level — teacher identity is passed as a string param (`actor`, `changed_by`). The UI should collect a display name on first visit and persist it in `localStorage`.

---

## 0. Design System

### Colour palette
```
Background:        #0B0F1A   (near-black navy)
Surface:           #141928   (card / panel)
Surface-elevated:  #1C2438   (modals, dropdowns)
Border:            #2A3350
Accent-blue:       #3B82F6   (primary actions)
Accent-purple:     #8B5CF6   (AI / auto-grade actions)
Accent-green:      #22C55E   (success / COMPLETED / RETURNED)
Accent-amber:      #F59E0B   (warning / PENDING / draft)
Accent-red:        #EF4444   (error / FAILED)
Text-primary:      #F1F5F9
Text-secondary:    #94A3B8
Text-muted:        #475569
```

### Typography
- Font: **Inter** (Google Fonts)  
- Headings: 600–700 weight  
- Body: 400 weight, 14–15px  
- Code/mono: **JetBrains Mono**

### Component conventions
- All cards: `rounded-xl`, `border border-[#2A3350]`, subtle `box-shadow`
- Status badges: coloured pill with dot indicator
- All destructive actions require a confirmation modal
- All async operations show an inline spinner, not a full-page loader
- Empty states: illustration + description + CTA button
- Polling: any page that shows job/submission status polls every **3 s** while any item is in a non-terminal state

---

## 1. Navigation

### Sidebar (always visible, collapsible to icon-only)

```
▣  AMGS                        ← logo + wordmark

─── Teaching ──────────────────
📋  Assignments
👥  Submissions
🏆  Grades

─── Classroom Sync ────────────
🔄  Classroom

─── Code Evaluation ───────────
⚙️  Environments
✅  Approvals
📊  Jobs

─── System ────────────────────
❤️  Health
```

Each item routes to the screen described below.  
Active route: left border accent + background highlight.

### Top bar
- Right side: **Actor name display** (e.g. "Teaching as: Prof. Sharma") with a pencil icon to change
- System health dot (green/red) that links to `/health`
- Google Classroom connection badge ("Connected" green / "Disconnected" amber) — polls `/api/v1/classroom/auth-status` every 30 s

---

## 2. Screen: Assignments (`/assignments`)

**Purpose**: Create and manage assignments; the central entity everything else hangs off.

### 2A. Assignment List

**API**: `GET /api/v1/assignments/`

**Layout**: Full-width table with the following columns:

| Column | Source field | Notes |
|---|---|---|
| Title | `title` | Clickable → detail page |
| Course | `course_id` | |
| Type | `question_type` | Badge: `subjective` (blue) / `coding` (purple) |
| Deadline | `deadline` | Relative time ("in 3 days", "overdue") |
| Published | `is_published` | Toggle badge — green tick / grey dash |
| Linked Classroom | `classroom_id` | Link icon if set |
| Actions | — | Edit · Publish · Delete |

**Filter bar** (above table):
- Search by title (client-side filter)
- Filter by `question_type`
- Filter by published status
- Filter by course_id (free text)

**Primary action**: `+ New Assignment` button → opens creation drawer

### 2B. Create / Edit Assignment Drawer

**APIs**: `POST /api/v1/assignments/` · `PATCH /api/v1/assignments/{id}` · `DELETE /api/v1/assignments/{id}`

**Fields**:
```
Title *                  [text input]
Course ID *              [text input — e.g. "CS101-2026"]
Classroom Assignment ID  [text input — optional Google Classroom coursework ID]
Description              [textarea]
Deadline                 [datetime-local picker]
Max Marks                [number input, default 100]
Question Type *          [radio: Subjective | Coding]
Has Code Question        [toggle — only shown when type = Subjective]
```

**Submit behaviour**: On save, close drawer and refresh table. Show toast "Assignment created".

### 2C. Assignment Detail (`/assignments/[id]`)

**API**: `GET /api/v1/assignments/{id}`

**Layout**: Two-column — left column details / right column action panel.

**Left column sections**:

1. **Header card**: Title, course, type badge, deadline, published status, created date
2. **Publish status card**:
   - If not published: button "Validate for publish" → calls `POST /api/v1/assignments/{id}/validate-publish` and shows checklist of pass/fail items. If all pass, "Publish" button appears → calls `POST /api/v1/assignments/{id}/publish`
   - If published: green banner with published date and actor
3. **Rubric card** (always shown):
   - If no rubric: "No rubric yet" with `Generate Rubric` (AI) and `Create Manually` buttons
   - If rubric exists: collapsed preview of `content_json` as formatted JSON with "Edit" and "Approve" actions
   - See §4 for full rubric spec
4. **Classroom sync card** (shown if `classroom_id` is set):
   - Submission counts from `GET /api/v1/classroom/{id}/status`
   - Sync actions (see §6)

**Right column**:
- Quick-nav links: Submissions (N) · Grades · Code Jobs (if coding)
- Assignment metadata (ID, created_at)

---

## 3. Screen: Submissions (`/submissions`)

**Purpose**: Browse and grade student submissions — both OCR-scanned handwritten papers and ingested Classroom files.

### 3A. Submission List

**API**: `GET /api/v1/submissions/{assignment_id}` — requires assignment selection

**Layout**:

Assignment selector dropdown at top (lists all assignments).  
Then a table:

| Column | Field | Notes |
|---|---|---|
| Student | `student_name` / `student_id` | |
| Status | `status` | Coloured badge (see statuses below) |
| Grade | from `/grade` sub-resource | Score / max, or "—" |
| Classroom | `classroom_status` on Grade | `not_synced` · `draft` · `released` |
| Source | `ocr_engine` | "classroom" / "upload" / engine name |
| Submitted | `created_at` | |
| Actions | — | View · Grade · Re-grade |

**Submission statuses**:
- `pending` → amber "Pending OCR"
- `ocr_complete` → blue "OCR Done"
- `grading` → amber spinner "Grading"
- `graded` → green "Graded"
- `error` → red "Error"

**Bulk actions** (multi-select checkboxes):
- Push draft grades → `POST /api/v1/grades/draft` with `{submission_ids: [...]}`
- Release grades → `POST /api/v1/grades/release` with `{submission_ids: [...]}`

**Upload button**: `+ Upload Submission` → opens upload modal (§3C)

### 3B. Submission Detail (`/submissions/[id]`)

**APIs**: `GET /api/v1/submissions/detail/{id}` · `GET /api/v1/submissions/{id}/grade` · `GET /api/v1/submissions/{id}/audit` · `PATCH /api/v1/submissions/{id}/ocr-correction`

**Layout**: Three-panel

```
┌──────────────────┬─────────────────────┬──────────────┐
│  Scanned image   │   OCR blocks        │  Grade panel │
│  (full height)   │   (editable)        │  + Audit log │
└──────────────────┴─────────────────────┴──────────────┘
```

**Left panel — Image viewer**:
- `GET /api/v1/submissions/image/{id}` renders the raw scanned image
- Zoom controls (+ / − / fit)
- If OCR blocks are available, draw bounding-box overlays on hover

**Middle panel — OCR blocks**:
- Each block shown as a card with: block index, content text, confidence (if available)
- Pencil icon on each block → inline edit mode
  - Text area pre-filled with current content
  - Reason field (optional free text)
  - Save → `PATCH /api/v1/submissions/{id}/ocr-correction` with `{block_index, new_content, reason, changed_by: actorName}`
  - After save: show spinner while re-grade enqueues; update status badge
- Hover on block → highlight corresponding region on left-panel image

**Right panel — Grade**:
- Score: large display `75 / 100`
- Source badge: `AI Generated` (purple) / `AI Corrected` (blue) / `TA Manual` (green)
- `breakdown_json` rendered as expandable question-level list:
  ```
  Q1  Dijkstra's Algorithm    18 / 20
  Q2  Time Complexity          9 / 10
  ...
  ```
- `classroom_status` badge: `not_synced` (grey) / `draft` (amber) / `released` (green)
- Action buttons: **Push Draft** `POST /api/v1/grades/draft` · **Release** `POST /api/v1/grades/release`

**Audit log** (below grade panel, collapsible):
- Table of all audit entries: timestamp, action, actor, old→new value, reason
- Newest first

### 3C. Upload Submission Modal

**API**: `POST /api/v1/submissions/{assignment_id}/upload`

```
Student ID *      [text input]
Student Name      [text input]
File *            [file drop zone — accepts image/pdf]
```

Submit → multipart form POST with `?student_id=&student_name=` query params.  
On success: close modal, refresh list, show toast "Submission queued for OCR".

---

## 4. Screen: Rubrics (embedded in Assignment Detail, §2C)

**APIs**: `POST /api/v1/rubrics/{assignment_id}` · `GET /api/v1/rubrics/{assignment_id}` · `POST /api/v1/rubrics/{assignment_id}/generate` · `POST /api/v1/rubrics/{rubric_id}/approve`

### Rubric card (inside Assignment Detail)

**States**:

1. **No rubric** — shows two buttons:
   - `⚡ Generate with AI` → calls `POST /api/v1/rubrics/{id}/generate`, then polls `GET /api/v1/rubrics/{id}` every 3 s until `source !== "generating"`
   - `✏️ Create manually` → opens inline JSON editor (see below)

2. **Rubric exists — pending approval** — shows:
   - Rubric content as formatted, collapsible tree:
     ```
     Scoring Policy
     ├── coding
     │   ├── rubric_weight: 40
     │   └── testcase_weight: 60
     └── questions: [...]
     ```
   - Source badge: `AI Generated` / `Manual`
   - **Approve** button → `POST /api/v1/rubrics/{rubric_id}/approve` with `{actor: actorName}`
   - **Edit** button → opens inline JSON editor
   - **Regenerate** button

3. **Rubric approved** — green checkmark + "Approved by {approved_by}". Edit/regenerate still available (creates new version).

### Manual Rubric Editor
- Monaco-style JSON editor pre-filled with a template:
  ```json
  {
    "questions": [
      {"id": "q1", "text": "...", "max_marks": 20}
    ],
    "scoring_policy": {
      "coding": {
        "rubric_weight": 40,
        "testcase_weight": 60
      }
    }
  }
  ```
- Validate button runs client-side JSON check
- Save → `POST /api/v1/rubrics/{assignment_id}` with `{content_json, source: "manual"}`

---

## 5. Screen: Grades (`/grades`)

**Purpose**: Cross-assignment grade overview and batch sync operations.

### 5A. Grades Overview

**Layout**: Assignment picker → then a grade table for the selected assignment.

Pulls data from `GET /api/v1/submissions/{assignment_id}` (includes grade via detail) and `GET /api/v1/classroom/{assignment_id}/status`.

| Column | |
|---|---|
| Student | name + ID |
| Score | `total_score / max_marks` as progress bar |
| Source | `ai_generated` / `ai_corrected` / `ta_manual` / `code_eval` badge |
| Sync Status | `not_synced` / `draft` / `released` badge |
| Flagged | `is_truncated` warning icon |
| Actions | View submission · Push draft · Release |

**Stats cards** (top row):
```
[  Total: 32  ]  [  Graded: 28  ]  [  Ungraded: 4  ]  [  Released: 20  ]
```

**Bulk action bar** (appears when rows are selected):
- `Push Selected as Draft` → `POST /api/v1/grades/draft`
- `Release Selected` → `POST /api/v1/grades/release`
- Confirmation modal before release ("This will make grades visible to students in Classroom")

### 5B. Grade Distribution Chart
- Below the table: horizontal bar chart showing score distribution in 10-point buckets (0-10, 10-20, … 90-100)
- Uses grade `total_score` values
- Rendered client-side (no library dependency — pure SVG or Canvas)

---

## 6. Screen: Classroom Sync (`/classroom`)

**Purpose**: Manage the full Google Classroom integration lifecycle per assignment.

### 6A. Sync Dashboard

**API**: `GET /api/v1/classroom/auth-status`

**Top banner**:
- If `authenticated: false` → red banner: "Google Classroom not connected. Run `get_classroom_token.py` on the server." (with copy-paste command)
- If `authenticated: true` → green banner: "Connected · Scopes: [list]"

**Assignment picker**: select an AMGS assignment that has a `classroom_id` set.

### 6B. Assignment Sync Panel

**API**: `GET /api/v1/classroom/{assignment_id}/status`

**Stats row**:
```
[ Total submissions: 3 ]  [ Graded: 2 ]  [ Ungraded: 1 ]
```

**Submissions table**:

| Column | |
|---|---|
| Student | name + ID |
| Status | `pending` / `graded` badge |
| Score | `total_score` or "—" |
| Grade Source | badge |
| Sync Status | `not_synced` · `draft` · `released` |

**Action panel** (right side, sticky):

```
┌─────────────────────────────┐
│  Classroom Actions          │
│                             │
│  [  Ingest Submissions  ]   │
│  Pulls TURNED_IN work from  │
│  Classroom; deduplicates.   │
│  ☐ Force re-ingest          │
│                             │
│  [  Push Draft Grades   ]   │
│  Sends grades as draftGrade │
│  (teacher-visible only).    │
│                             │
│  [  Release to Students ]   │
│  ⚠️ Makes grades visible to │
│  students. Irreversible.    │
└─────────────────────────────┘
```

Each button:
- **Ingest**: `POST /api/v1/classroom/{id}/ingest` with `{course_id, coursework_id, force_reingest}` → shows result toast "Ingested N, skipped M"
- **Sync Draft**: `POST /api/v1/classroom/{id}/sync-draft` → toast "Pushed N draft grade(s)"
- **Release**: confirmation modal ("Are you sure? This publishes grades to students.") → `POST /api/v1/classroom/{id}/release` → toast "Released N grade(s)"

**Ingest config fields** (shown above Ingest button):
```
Classroom Course ID   *   [text input — pre-filled if assignment has course_id]
Classroom Assignment ID * [text input — pre-filled from assignment.classroom_id]
```

---

## 7. Screen: Code Eval — Environments (`/environments`)

**Purpose**: Manage evaluation environment versions for coding assignments.

### 7A. Environment List

**API**: `GET /api/v1/code-eval/environments/versions`

Table:

| Column | |
|---|---|
| ID (short) | first 8 chars |
| Assignment | `assignment_id` |
| Profile | `profile_key` |
| Status | `draft` (grey) · `building` (amber spinner) · `ready` (green) · `failed` (red) |
| Version | `version_number` |
| Active | toggle badge |
| Freeze Key | monospace, truncated |
| Actions | View · Build · Validate |

Filter by status, assignment_id.

`+ New Environment` button → creation drawer:
```
Course ID *          [text]
Assignment ID        [text — optional]
Profile Key *        [text — e.g. "python3.12-default"]
Version Number       [number, default 1]
Spec JSON *          [JSON editor — see template below]
```

Spec template:
```json
{
  "language": "python",
  "compile_flags": [],
  "run_flags": [],
  "timeout_seconds": 10,
  "memory_limit_mb": 256
}
```

### 7B. Environment Detail (`/environments/[id]`)

**API**: `GET /api/v1/code-eval/environments/versions/{id}`

**Sections**:

1. **Status card**: current status with last-updated time. If `building` → live-poll every 3 s with spinner
2. **Build logs**: pre/code block showing `build_logs`, auto-scrolls to bottom, monospaced
3. **Spec**: formatted JSON display
4. **Actions**:
   - **Build** → `POST /api/v1/code-eval/environments/versions/{id}/build` with optional `{triggered_by: actorName}`
   - **Validate publish** → `POST /api/v1/code-eval/environments/versions/{id}/validate-publish` → show checklist (same pattern as assignment publish validation)
5. **Runtime status sidebar**: `GET /api/v1/code-eval/runtime/status` — shows `execution_backend`, `shim_retry_enabled`, MicroVM config

---

## 8. Screen: Code Eval — Approvals (`/approvals`)

**Purpose**: Review and approve AI-generated test cases and other code-eval artifacts.

### 8A. Approval Queue

**API**: `GET /api/v1/code-eval/approvals`

Filter tabs: **All · Pending · Approved · Rejected**

Table:

| Column | |
|---|---|
| Assignment | `assignment_id` |
| Artifact Type | `testcase_draft` / `rubric_draft` badge |
| Status | `pending` (amber) · `approved` (green) · `rejected` (red) |
| Version | `version_number` |
| Requested by | `requested_by` |
| Created | relative time |
| Actions | Review |

### 8B. Approval Review (`/approvals/[id]`)

**APIs**: `GET`, `POST .../approve`, `POST .../reject`, `POST .../generate-tests`

**Layout**: Full-page two-column

**Left — Artifact content**:
- For `testcase_draft`: render each test case as a card:
  ```
  ┌─ Testcase 1 ────────────────────────┐
  │ Class: happy_path                    │
  │ Description: Fibonacci n=10          │
  │ stdin: 10                            │
  │ expected_stdout: 55                  │
  └──────────────────────────────────────┘
  ```
- For `rubric_draft`: show as expandable JSON tree
- **Generate Tests** button → `POST .../generate-tests` — replaces current content after confirming dialog. Shows loading state.

**Right — Decision panel**:
```
Actor:   [text input — pre-filled from localStorage]
Reason:  [textarea — required for reject]

[  ✓ Approve  ]   [  ✗ Reject  ]
```

- Approve → `POST .../approve` with `{actor, reason}`
- Reject → `POST .../reject` with `{actor, reason}`

After decision: show result banner, disable buttons, redirect to queue in 3 s.

---

## 9. Screen: Code Eval — Jobs (`/jobs`)

**Purpose**: Monitor code evaluation job queue; inspect per-job results and attempt details.

### 9A. Job List

**API**: `GET /api/v1/code-eval/jobs`

**Filter bar**:
- Assignment ID (free text)
- Status filter (multi-select chips): `QUEUED · RUNNING · COMPLETED · FAILED · CANCELLED`
- Language filter: `python · c · cpp · java`

**Table** (polls every 3 s if any job is non-terminal):

| Column | |
|---|---|
| Job ID | short (8 chars), monospace |
| Assignment | link |
| Language | badge |
| Status | coloured status badge |
| Score | `final_result_json.score` if available |
| Attempts | `attempt_count` |
| Duration | `finished_at - started_at` |
| Queued | relative time |
| Actions | View |

### 9B. Job Detail (`/jobs/[id]`)

**API**: `GET /api/v1/code-eval/jobs/{id}` → `CodeEvalJobDetailOut` (includes `attempts`)

**Header**: Status badge (large), language, assignment link, duration

**Tabs**:

#### Tab 1: Summary
- `final_result_json` rendered as:
  - **Score**: `72 / 100`
  - **Testcase results** table:
    ```
    #   Description      Result    Score    Time
    1   n=0 edge case    PASS      10/10    12ms
    2   n=5 normal       PASS      10/10    8ms
    3   large input      FAIL      0/10     timeout
    ```
  - If `shim_warning` present: amber callout box
  - If `grade_write_warning` present: amber callout box

#### Tab 2: Attempts
- Each attempt as collapsible card:
  - Header: `Attempt {n} — {stage} — {passed ? PASS : FAIL}`
  - Inside: stdout/stderr in `<pre>` blocks, exit code, shim info, duration
  - `artifacts_json` as formatted JSON (collapsed by default)

#### Tab 3: Raw JSON
- Full `final_result_json` in a syntax-highlighted, copyable code block

---

## 10. Screen: Health (`/system`)

**Purpose**: Quick operational status check.

**APIs**: `GET /health` · `GET /api/v1/code-eval/runtime/status` · `GET /api/v1/code-eval/runtime/preflight` · `GET /api/v1/classroom/auth-status`

**Layout**: Card grid

```
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Backend     │ │  Classroom   │ │  Code Eval   │ │  Runtime     │
│  ✅ OK       │ │  ✅ Authed   │ │  Backend:    │ │  Preflight   │
│              │ │  3 scopes    │ │  docker      │ │  checks...   │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

**Runtime status** (`/api/v1/code-eval/runtime/status`) expanded:
```
Execution backend:     docker
Shim retry:            enabled
AI shim generation:    enabled
MicroVM host:          unavailable (no KVM)
```

**Preflight checks** (`/api/v1/code-eval/runtime/preflight`) — table of each check with pass/fail icon.

---

## 11. Global UX Patterns

### Toast notifications
- Position: bottom-right
- Auto-dismiss: 4 s (errors: 8 s, manual dismiss)
- Types: `success` (green) · `error` (red) · `warning` (amber) · `info` (blue)

### Loading states
- Table loading: skeleton rows (animated shimmer)
- Card loading: skeleton card
- Button loading: replace label with spinner + "Processing…"
- Never use full-page spinners

### Error states
- API error → red inline callout with HTTP status + `detail` field from response body
- 404 → centered "Not found" with back link
- 500 → red callout with raw error message and "Retry" button

### Polling strategy
- Use `setInterval` at 3 s for any page with non-terminal statuses
- Stop polling when all items are terminal
- Show "Last updated Xs ago" timestamp

### Empty states
- Each list/table has a custom empty-state illustration (inline SVG) + description + CTA
  - e.g. Assignments: "No assignments yet — create your first one"
  - Jobs: "No jobs — submit code to an assignment to start"

### Confirmation modals
Required for any destructive or irreversible action:
- Release grades to students
- Delete assignment
- Re-generate tests (overwrites existing draft)
- Publish assignment

---

## 12. Routing Summary

```
/                          → redirect to /assignments
/assignments               → Assignment list
/assignments/[id]          → Assignment detail + rubric + publish
/submissions               → Submission list (assignment picker)
/submissions/[id]          → Submission detail (3-panel: image / OCR / grade)
/grades                    → Grade overview + batch sync
/classroom                 → Classroom sync dashboard
/environments              → Code-eval environment list
/environments/[id]         → Environment detail + build logs
/approvals                 → Approval queue
/approvals/[id]            → Approval review
/jobs                      → Job list (live-polling)
/jobs/[id]                 → Job detail (summary / attempts / raw)
/system                    → Health + runtime status
```

---

## 13. API Client Conventions

All API calls should be wrapped in a typed client module (`lib/api.ts`).

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080";

async function apiFetch<T>(
  path: string,
  options?: RequestInit & { params?: Record<string, string> }
): Promise<T> {
  const url = new URL(API_BASE + path);
  if (options?.params) {
    Object.entries(options.params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const res = await fetch(url.toString(), {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, err.detail ?? "Unknown error");
  }
  return res.json();
}
```

Error type:
```typescript
class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
```

React Query (`@tanstack/react-query`) recommended for all data fetching — handles caching, polling (`refetchInterval`), and loading/error states.

---

## 14. Key Data Types (TypeScript)

```typescript
type QuestionType   = "subjective" | "coding";
type SubmissionStatus = "pending" | "ocr_complete" | "grading" | "graded" | "error";
type GradeSource    = "ai_generated" | "ai_corrected" | "ai_healed" | "ta_manual" | "code_eval";
type ClassroomStatus = "not_synced" | "draft" | "released";
type JobStatus      = "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
type EnvStatus      = "draft" | "building" | "ready" | "failed";
type ApprovalStatus = "pending" | "approved" | "rejected";

interface Assignment {
  id: string; course_id: string; classroom_id: string | null;
  title: string; description: string | null;
  deadline: string | null; max_marks: number;
  question_type: QuestionType; has_code_question: boolean;
  is_published: boolean; published_at: string | null;
  published_by: string | null;
  published_environment_version_id: string | null;
  created_at: string;
}

interface Submission {
  id: string; assignment_id: string;
  student_id: string; student_name: string | null;
  status: SubmissionStatus;
  ocr_result: OcrResult | null; ocr_engine: string | null;
  error_message: string | null;
  created_at: string; updated_at: string;
}

interface OcrResult {
  blocks: Array<{ index: number; content: string; bbox?: number[] }>;
}

interface Grade {
  id: string; submission_id: string;
  active_version: boolean; total_score: number;
  breakdown_json: Record<string, unknown>;
  source: GradeSource; classroom_status: ClassroomStatus;
  is_truncated: boolean; graded_at: string;
}

interface CodeEvalJob {
  id: string; assignment_id: string; submission_id: string;
  environment_version_id: string | null;
  status: JobStatus; language: string; entrypoint: string;
  attempt_count: number;
  final_result_json: FinalResult | null;
  error_message: string | null;
  queued_at: string; started_at: string | null; finished_at: string | null;
}

interface FinalResult {
  score: number; max_score: number;
  testcase_results: TestcaseResult[];
  shim_warning?: string; grade_write_warning?: string;
}

interface TestcaseResult {
  index: number; description: string;
  passed: boolean; score: number; max_score: number;
  time_ms?: number; reason?: string;
}
```

---

## 15. Environment Variables

```
NEXT_PUBLIC_API_BASE=http://localhost:8080
```

For production, override to the deployed backend URL.

---

## 16. Priority Build Order

Build screens in this order to get a usable teacher interface as fast as possible:

1. **Layout + navigation** — sidebar, topbar, actor name, health dot
2. **Assignment list + create/edit** — the root entity
3. **Submission list + upload modal** — core grading workflow
4. **Submission detail** — OCR viewer + block editing + grade panel (most complex screen)
5. **Classroom sync** — ingest + push draft + release workflow
6. **Grades overview** — batch actions + distribution chart
7. **Rubric editor** — embedded in assignment detail
8. **Jobs list + detail** — code eval monitoring
9. **Environments** — environment management
10. **Approvals** — test case review queue
11. **Health / system** — operational status
