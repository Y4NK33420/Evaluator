This document outlines the full technical specification and execution roadmap for the Automated Marksheet Grading System (AMGS). It integrates your requirements for a local-first OCR pipeline, high-reasoning cloud grading, and robust college-scale reliability.
1. System Architecture & Tech Stack
The system is designed as a distributed asynchronous pipeline to ensure high availability and "no job lost" persistence.
Frontend: Next.js with Tailwind CSS and framer-motion for the grading dashboard.
Backend: FastAPI (Python 3.12+) acting as the orchestration layer.
Message Broker: Redis with Celery for task queuing (OCR and Grading jobs).
Database: PostgreSQL for structured data (Grades, Rubrics, Audit Trails).
OCR Engine: GLM-OCR (0.9B) running locally via vLLM (Quantized to 4-bit).
Grading Engine: Gemini 3 Flash API (for cost-efficient, high-context reasoning).
Storage: Local filesystem or MinIO for storing raw scans and annotated overlays.
2. Product Requirements (PRD)
A. Ingestion & Pre-processing
Google Classroom Sync: Fetches submissions only after the deadline to avoid version conflicts.
Auto-Orientation: Uses a lightweight CV step (Hough Transform or OSD) to detect and fix rotated scans before OCR.
Deduplication: Hashing of images to prevent double-grading the same sheet.
B. The Grading Engine (Gemini 3 Flash)
Consolidated Prompting: A single API call per student handles Truncation Detection, Reasoning, and Scoring.
Flexible Rubrics: * Manual: Instructor uploads a specific step-wise marking JSON.
AI-Generated: System generates a rubric from a "Master Answer" and requires Instructor Approval before batch processing.
Code Evaluation:
Strict Mode: Direct execution in an isolated Docker Sandbox.
Heuristic Mode: AI "fixes" common OCR syntax artifacts (e.g., misread brackets) before execution.
C. Human-in-the-Loop (HITL) Dashboard
Split-Screen Review: Original scan on the left, AI-extracted text/marks on the right.
Bounding Box Highlights: Clicking a low-confidence word in the text highlights its specific $(x, y)$ coordinate on the image.
Draft State Control: Grades are pushed to Google Classroom as draftGrade first. A "Release All" button converts them to assignedGrade.
3. Implementation Phases (Step-by-Step)
Phase 1: Infrastructure & "No Job Lost" Setup
Database Migration: Set up PostgreSQL tables for Assignments, Submissions, AuditLogs, and Rubrics.
Worker Architecture: Configure a Redis-backed Celery worker. When a TA triggers "Process Course," the system creates 120+ "Jobs" in the DB.
Atomic Updates: Implement the "Single-Run Overwrite" logic. If a job is re-run, the database updates the active_version of the grade and archives the old one.
Phase 2: Local OCR Pipeline (GLM-OCR)
Deployment: Deploy GLM-OCR (0.9B) using vLLM.
Quantization: Use 4-bit (Q4_K_M) to fit the model into ~2.2GB VRAM, leaving the remaining ~1.8GB (on your 4GB system) for the context window.
Coordinate Extraction: Configure the model to return JSON-formatted output including bounding boxes for every line of text.
Phase 3: The "All-in-One" Grading Logic
Prompt Engineering: Build the Gemini 3 Flash prompt that includes:
"Check for truncation (incomplete sentences)."
"Apply the step-wise rubric $R$ to answer $A$."
"Return JSON with scores and feedback."
Consistency Guard: A Python post-processor that verifies $\sum (Submarks) = Total$. If not, it flags the paper for manual review.
Phase 4: Integration & Review UI
Review Dashboard: Build the Next component for side-by-side comparison.
Classroom Bridge: Implement the PATCH /v1/courses/{id}/courseWork/{id}/studentSubmissions/{id} endpoint to sync draftGrade.
Audit Logs: Ensure every change made by a TA is logged with timestamp, old_value, and reason.
4. Hardware & Scaling Specifications
Component
Minimum (Your Setup)
Throughput (120 Students)
GPU
RTX 3050 (4GB)
~45-60 mins for full batch.
Inference
Quantized Q4_K_M
0.8 to 1.2 pages/sec.
Storage
100GB SSD
Space for ~2,000 high-res scans.
API
Gemini 3 Flash
Sub-3 second grading per student.

5. Risk Mitigation & Edge Cases
Truncated Pages: If Gemini detects a cut-off sentence, the UI highlights the question in Orange and blocks the grade from syncing to Classroom until a TA confirms.
OCR Hallucination: If the OCR confidence for a key field (like Roll Number) is $< 90\%$, the system flags it for "Manual ID Verification."
Sandbox Safety: Student code is run in a Network-Disabled Container with a 5-second timeout and 128MB RAM limit to prevent infinite loops or system attacks.


Detailed Caveats and per component requirements

Yes, extracting confidence scores from GLM-OCR is absolutely possible, but it requires a slight shift in how you think about OCR output.
Because GLM-OCR is a Vision-Language Model (VLM) built on an LLM architecture, it doesn't calculate confidence based purely on pixel clarity like traditional engines (e.g., Tesseract). Instead, it outputs token probabilities—the mathematical likelihood of the next piece of text given the visual input and the preceding language context.
If you are running GLM-OCR locally on your 4GB VRAM machine using an inference engine like vLLM or llama.cpp, you can flag the API to return the logprobs (log probabilities) for every generated token.
Here is the best way to implement this without compromising quality:
Extract and Group Tokens: Request logprobs during inference. Group the tokens that make up a specific word or sentence alongside the bounding box coordinates GLM-OCR generates.
Calculate Block Confidence: Because probabilities multiply (making long sentences artificially seem less confident), calculate the geometric mean of the token probabilities for a given bounding box. You can do this by averaging the log probabilities:
$$\text{Score} = \exp\left(\frac{1}{N} \sum_{i=1}^N \log P(t_i)\right)$$
Beware the "Context Trap": LLMs are built to predict logical text. If a student writes a terribly messy but predictable word (like "polymorphism" in a Java exam), the model might give it a 99% probability because it fits the sentence perfectly. Conversely, a clearly written but unusual variable name might get a lower score.
The Threshold: Set a threshold (e.g., 0.85). If a text block falls below this, flag its specific bounding box coordinates so it highlights in Orange on your TA dashboard.
The Complete System Architecture & PRD
Here is the synthesis of our discussion, breaking down your automatic marksheet checker into its core components, requirements, and implementation steps.
1. Ingestion & Submission Engine
Requirements: Support digitized paper sheets, code files, and handwritten code in English. Must handle large batches (e.g., 120 students across 5-6 courses).
Implementation: * Google Classroom Sync: Post-deadline ingestion only. The system waits for the assignment deadline to pass before pulling PDFs to avoid versioning conflicts.
Sequential Enforcement: Multi-page linking relies on strict sequential scanning. This is enforced via UI flows in a future v2 mobile app or by mandating ordered PDF uploads in Google Classroom.
State Management: Include Draft, Change, and Release-All states for syncing grades back to the classroom.
2. Local Vision & OCR Pipeline
Requirements: Process heavy visual data locally without dropping jobs. Must handle skewed or rotated scans.
Implementation:
Hardware Constraints: Run GLM-OCR (0.9B) quantized to 4-bit (Q4_K_M) to fit comfortably within the 4GB VRAM limit alongside context overhead.
Processing Queue: Strictly sequential processing (First-In-First-Out based on submission order). Use a Redis or Celery task queue with tiered processing times based on server load.
Pre-Processing: Before hitting the VLM, pass images through a lightweight Computer Vision script (like a Hough Transform or Tesseract OSD) to auto-detect and correct page orientation.
Output Format: Force JSON layout mode so GLM-OCR returns both the extracted text and its associated bounding box coordinates.
3. The Grading Engine (Gemini)
Requirements: High-reasoning evaluation of subjective answers and code without using negative or bonus marks. Must be aware of missing or cut-off context.
Implementation:
Consolidated Prompting: Send the Question, OCR text, Answer Key, and Rubric in a single API call to Gemini 3 Flash to save latency.
Instructor Configurations: Allow instructors to toggle code strictness (e.g., "fail on syntax" vs. "fix obvious errors"). If no rubric is provided, the system auto-generates one from the answer key and requires instructor approval before grading begins.
Truncation Audit: Prompt Gemini to explicitly look for mid-sentence cuts or missing brackets before grading, outputting an is_truncated boolean.
4. Logic & Consistency Validator
Requirements: Guarantee mathematical consistency. AI hallucinations must not corrupt the total marks.
Implementation:
Local Python Checks: A script intercepts the Gemini JSON output before database insertion.
Validation Rules: It verifies that the sum of sub-section marks exactly equals the total score, and that the total score does not exceed the maximum allowed marks.
Overwrite Policy: Grades evaluated in a single run overwrite previous entries; the system never cumulatively adds marks on re-runs.
5. Reviewer Dashboard (The TA Interface)
Requirements: An intuitive workspace for TAs to quickly verify AI confidence, fix OCR errors, and manually override grades.
Implementation:
Split-Screen View: A Next frontend displaying the raw handwritten image on one side and the digital grading on the other.
Interactive Overlays: Map the GLM-OCR bounding boxes to a canvas layer over the image. When a TA clicks a line of extracted text, the corresponding area on the physical scan highlights.
Correction Trigger: If a TA edits the extracted OCR text directly in the dashboard, it automatically fires off a lightweight re-grading job for that specific question.
Color-Coded Triage: Green for confident grades, Orange for suspected truncation/low OCR confidence, and Red for math validation failures. Includes a manual "Rotate & Re-OCR" fallback button.
6. Database & Audit Trail
Requirements: Full accountability for how every mark was awarded, with local storage for raw files.
Implementation:
Storage: Utilize ample local disk space to store raw PDF scans.
Traceability: Every grade entry in the database is tagged with its source (AI_Generated, AI_Corrected, or TA_Manual).
Archiving: When a re-grade is triggered, the previous log is archived into an Audit_Trail table, ensuring a complete history of changes while only the latest run remains active.


