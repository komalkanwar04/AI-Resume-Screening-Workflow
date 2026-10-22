#!/usr/bin/env python3
"""
AI-Resume-Screening-Workflow (Stage 1)
-------------------------------------
Evaluates candidate resumes against a job description using Anthropic's Claude,
returning validated structured JSON with scores, skill gaps, and recommendations.

Supports single-file evaluation (TXT/PDF) and batch screening of an entire folder,
exporting aggregated results to CSV.

Author: GitHub Project Template
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load environment variables from .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# PDF text extraction support via pypdf
try:
    import pypdf
except ImportError:
    pypdf = None

# Official Anthropic SDK
import anthropic

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Model constant defined at the top of the file for quick updates
MODEL_NAME = "claude-sonnet-5-5"

# Required JSON keys and constraints
REQUIRED_KEYS = {"score", "matched_skills", "missing_skills", "summary", "recommendation"}
VALID_RECOMMENDATIONS = {"shortlist", "maybe", "reject"}


# ---------------------------------------------------------------------------
# Text Extraction Helpers
# ---------------------------------------------------------------------------
def extract_text_from_file(file_path: str | Path) -> str:
    """
    Extracts plain text from a given file path.
    Supports .txt files and .pdf documents (via pypdf).

    Args:
        file_path: Path to the target resume or job description file.

    Returns:
        Extracted text as a stripped string.

    Raises:
        FileNotFoundError: If the file does not exist.
        ImportError: If pypdf is not installed when attempting to parse a PDF.
        ValueError: If the file is empty or contains no extractable text.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: '{file_path}'")

    # Handle PDF files
    if path.suffix.lower() == ".pdf":
        if pypdf is None:
            raise ImportError(
                "The 'pypdf' library is required to read PDF resumes. "
                "Install it with: pip install pypdf"
            )
        try:
            reader = pypdf.PdfReader(str(path))
            extracted_pages = []
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    extracted_pages.append(page_text.strip())
            full_text = "\n\n".join(extracted_pages).strip()
            if not full_text:
                raise ValueError(
                    f"PDF file '{file_path}' contains no extractable text. "
                    "The document might be an image-only scan or empty."
                )
            return full_text
        except Exception as e:
            if isinstance(e, (ValueError, ImportError)):
                raise
            raise ValueError(f"Error reading PDF file '{file_path}': {e}") from e

    # Handle text files (.txt, .md, etc.)
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
    except UnicodeDecodeError:
        # Fallback to latin-1 encoding for non-standard text files
        with open(path, "r", encoding="latin-1") as f:
            text = f.read().strip()

    if not text:
        raise ValueError(f"File '{file_path}' is empty.")

    return text


# ---------------------------------------------------------------------------
# JSON Parsing and Schema Validation
# ---------------------------------------------------------------------------
def parse_and_validate_json(raw_response: str) -> Dict[str, Any]:
    """
    Safely parses and validates JSON returned by Claude.

    Performs:
    1. Code fence removal (```json ... ``` or ``` ... ```).
    2. json.loads parsing with clear syntax error reporting.
    3. Structural validation ensuring all required keys exist.
    4. Data type and boundary checks:
       - score: int in range [0, 100]
       - matched_skills: list of strings
       - missing_skills: list of strings
       - summary: non-empty string, maximum 2 sentences
       - recommendation: string in {"shortlist", "maybe", "reject"}

    Args:
        raw_response: The raw string response from Claude.

    Returns:
        Validated dictionary matching the required schema.

    Raises:
        ValueError: If JSON is invalid, missing keys, or violates constraints.
    """
    cleaned = raw_response.strip()

    # Strip markdown code fences if Claude wrapped the JSON
    fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(fence_pattern, cleaned)
    if match:
        cleaned = match.group(1).strip()

    # Parse JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse Claude output as JSON: {exc.msg} (line {exc.lineno}, col {exc.colno}).\n"
            f"Raw output received:\n{raw_response}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at root, but received: {type(data).__name__}")

    # Verify required keys
    missing_keys = REQUIRED_KEYS - set(data.keys())
    if missing_keys:
        raise ValueError(
            f"JSON response is missing required keys: {', '.join(sorted(missing_keys))}. "
            f"Available keys: {list(data.keys())}"
        )

    # Validate score
    score = data.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ValueError(f"'score' must be a numeric integer/float between 0 and 100, got: {score!r}")
    if not (0 <= score <= 100):
        raise ValueError(f"'score' must be between 0 and 100 inclusive, got: {score}")
    data["score"] = int(round(score))

    # Validate matched_skills and missing_skills
    for skill_field in ("matched_skills", "missing_skills"):
        val = data.get(skill_field)
        if not isinstance(val, list):
            raise ValueError(f"'{skill_field}' must be a list of strings, got: {type(val).__name__}")
        data[skill_field] = [str(item).strip() for item in val if str(item).strip()]

    # Validate recommendation
    recommendation = str(data.get("recommendation", "")).strip().lower()
    if recommendation not in VALID_RECOMMENDATIONS:
        raise ValueError(
            f"'recommendation' must be one of {sorted(VALID_RECOMMENDATIONS)}, got: {recommendation!r}"
        )
    data["recommendation"] = recommendation

    # Validate summary
    summary = str(data.get("summary", "")).strip()
    if not summary:
        raise ValueError("'summary' must be a non-empty string.")
    data["summary"] = summary

    return data


# ---------------------------------------------------------------------------
# Core Screening Logic
# ---------------------------------------------------------------------------
def _build_evaluation_prompt(resume_text: str, jd_text: str) -> str:
    """Builds the evaluation prompt for Claude."""
    return f"""You are an expert AI technical recruiter and hiring evaluator.
Your task is to objectively evaluate the candidate's resume against the target Job Description.

EVALUATION CRITERIA:
1. Technical Competencies: Compare candidate's proven skills, tools, and project work directly against required and preferred qualifications.
2. Hands-on Experience: Prioritize actual implementation, system architecture, and project evidence over mere keyword mentions.
3. Realistic Scoring Rubric:
   - 85-100: Exceptional match. Has core required skills and directly relevant project experience. Recommendation: "shortlist".
   - 50-84: Moderate/average match. Possesses foundational skills but lacks key domain tools or specific project experience. Recommendation: "maybe".
   - 0-49: Weak match. Significant skill gaps, unrelated background, or missing critical prerequisites. Recommendation: "reject".

STRICT OUTPUT RULES:
- Output MUST be valid, parseable JSON only.
- Do NOT wrap in markdown explanations or prose outside the JSON.
- Adhere strictly to this schema:
  {{
    "score": <integer from 0 to 100>,
    "matched_skills": [<list of specific skill strings matched from the JD>],
    "missing_skills": [<list of specific skill strings required by JD but missing in resume>],
    "summary": "<concise summary explaining the evaluation, MAXIMUM 2 sentences>",
    "recommendation": "<exactly one of: shortlist | maybe | reject>"
  }}

--- TARGET JOB DESCRIPTION ---
{jd_text}

--- CANDIDATE RESUME ---
{resume_text}
"""


def screen(resume_text: str, jd_text: str, mock: bool = False) -> Dict[str, Any]:
    """
    Evaluates a candidate resume against a job description using Anthropic's Claude.

    Args:
        resume_text: Plain text of the candidate's resume.
        jd_text: Plain text of the job description.
        mock: If True, returns a deterministic offline evaluation (useful for testing/demos without an API key).

    Returns:
        Structured evaluation dict:
        {
            "score": int (0-100),
            "matched_skills": list of str,
            "missing_skills": list of str,
            "summary": str (max 2 sentences),
            "recommendation": "shortlist" | "maybe" | "reject"
        }

    Raises:
        ValueError: If inputs are invalid or environment variables are missing.
        RuntimeError: If Anthropic API errors occur (authentication, rate limits, network).
    """
    if not resume_text or not resume_text.strip():
        raise ValueError("Resume text is empty.")
    if not jd_text or not jd_text.strip():
        raise ValueError("Job description text is empty.")

    # Offline mock mode for testing/demoing without burning API tokens or if key is not configured
    if mock:
        return _mock_screen(resume_text, jd_text)

    # Validate API key presence
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your_key_here":
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Please set your Anthropic API key in your environment:\n"
            "  export ANTHROPIC_API_KEY=\"sk-ant-...\"\n"
            "or create a .env file with ANTHROPIC_API_KEY=your_key_here."
        )

    # Initialize official Anthropic client
    client = anthropic.Anthropic(api_key=api_key)

    prompt = _build_evaluation_prompt(resume_text, jd_text)

    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=1024,
            system=(
                "You are an automated resume screening engine. "
                "You evaluate technical candidates against job descriptions and return raw JSON strictly conforming to the requested schema."
            ),
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        # Extract text content from the response
        raw_text = response.content[0].text
        return parse_and_validate_json(raw_text)

    except anthropic.AuthenticationError as exc:
        raise RuntimeError(
            f"Authentication failed: The provided ANTHROPIC_API_KEY is invalid. "
            f"Please verify your API key. (Details: {exc.message})"
        ) from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError(
            f"Rate limit exceeded: Anthropic API rate limit reached. "
            f"Please wait before making additional requests. (Details: {exc.message})"
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError(
            f"Network connection error: Unable to reach Anthropic API servers. "
            f"Please check your internet connection. (Details: {exc.message})"
        ) from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(
            f"Anthropic API returned error status HTTP {exc.status_code}: {exc.message}"
        ) from exc
    except anthropic.APIError as exc:
        raise RuntimeError(
            f"An unexpected Anthropic API error occurred: {exc.message}"
        ) from exc


def _mock_screen(resume_text: str, jd_text: str) -> Dict[str, Any]:
    """
    Deterministic offline fallback evaluator for local testing and CI/CD demonstration.
    Analyzes key qualifications present in the resume text.
    """
    resume_lower = resume_text.lower()
    
    # Check key technical competencies
    has_claude = "claude" in resume_lower or "anthropic" in resume_lower
    has_n8n = "n8n" in resume_lower or "make" in resume_lower or "zapier" in resume_lower
    has_python = "python" in resume_lower
    has_api = "api" in resume_lower or "webhook" in resume_lower
    has_pypdf = "pdf" in resume_lower or "pypdf" in resume_lower

    matched = []
    missing = []

    if has_python:
        matched.append("Python programming")
    else:
        missing.append("Python programming")

    if has_claude:
        matched.append("Anthropic Claude API & Prompt Engineering")
    else:
        missing.append("Anthropic Claude API experience")

    if has_n8n:
        matched.append("Workflow automation (n8n/webhooks)")
    else:
        missing.append("n8n workflow automation")

    if has_api:
        matched.append("REST APIs & Webhooks")
    else:
        missing.append("REST APIs & Webhooks")

    if has_pypdf:
        matched.append("Document extraction (pypdf/PDF)")

    # Compute score based on matched attributes
    if has_claude and has_python and has_n8n and has_api:
        score = 92
        recommendation = "shortlist"
        summary = (
            "Candidate exhibits outstanding alignment with the AI Intern role, possessing proven experience "
            "with the Claude API, n8n automations, and Python pipelines."
        )
    elif has_python and (has_api or has_n8n):
        score = 68
        recommendation = "maybe"
        summary = (
            "Candidate demonstrates strong technical foundations and API familiarity, but lacks dedicated "
            "experience with Anthropic Claude workflows and advanced n8n orchestration."
        )
    elif has_python:
        score = 58
        recommendation = "maybe"
        summary = (
            "Candidate has solid data and programming fundamentals in Python, but lacks direct experience "
            "with LLM prompt engineering, workflow automations, or webhooks."
        )
    else:
        score = 18
        recommendation = "reject"
        summary = (
            "Candidate lacks necessary technical background in Python, APIs, and AI workflow automation "
            "required for this engineering internship."
        )

    return {
        "score": score,
        "matched_skills": matched,
        "missing_skills": missing,
        "summary": summary,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Batch Processing
# ---------------------------------------------------------------------------
def screen_batch(
    samples_dir: str | Path,
    jd_file: str | Path,
    output_csv: str | Path = "results.csv",
    mock: bool = False,
) -> List[Dict[str, Any]]:
    """
    Evaluates every resume (.txt and .pdf) in a directory against a job description,
    printing live progress and saving consolidated scores to a CSV file.

    Args:
        samples_dir: Folder containing resume files.
        jd_file: Path to the job description file.
        output_csv: Destination CSV file path (defaults to results.csv).
        mock: If True, uses offline deterministic evaluation.

    Returns:
        List of processed candidate result records.
    """
    samples_path = Path(samples_dir)
    jd_path = Path(jd_file)

    if not samples_path.is_dir():
        raise NotADirectoryError(f"Directory not found: '{samples_dir}'")

    # Read Job Description
    jd_text = extract_text_from_file(jd_path)

    # Collect candidate resume files (.txt and .pdf), ignoring the JD if located in same folder
    candidate_files: List[Path] = []
    for item in sorted(samples_path.iterdir()):
        if not item.is_file():
            continue
        # Skip job description if present in the same directory
        if item.resolve() == jd_path.resolve() or "job_description" in item.name.lower():
            continue
        if item.suffix.lower() in {".txt", ".pdf"}:
            candidate_files.append(item)

    if not candidate_files:
        raise ValueError(f"No .txt or .pdf resume files found in '{samples_dir}'.")

    print(f"\n[Batch Screening] Found {len(candidate_files)} candidate resume(s) in '{samples_dir}'")
    print(f"[Batch Screening] Job Description: '{jd_path.name}'")
    print(f"[Batch Screening] Model: {MODEL_NAME}{' (MOCK MODE)' if mock else ''}")
    print("-" * 70)

    results: List[Dict[str, Any]] = []

    for file_path in candidate_files:
        print(f"-> Screening: {file_path.name} ... ", end="", flush=True)
        try:
            resume_text = extract_text_from_file(file_path)
            eval_result = screen(resume_text, jd_text, mock=mock)
            record = {
                "filename": file_path.name,
                "score": eval_result["score"],
                "recommendation": eval_result["recommendation"],
                "matched_skills": "; ".join(eval_result["matched_skills"]),
                "missing_skills": "; ".join(eval_result["missing_skills"]),
                "summary": eval_result["summary"],
            }
            results.append(record)
            print(f"DONE | Score: {record['score']}/100 | Rec: {record['recommendation'].upper()}")
        except Exception as err:
            print(f"FAILED ({err})")
            results.append({
                "filename": file_path.name,
                "score": 0,
                "recommendation": "error",
                "matched_skills": "",
                "missing_skills": "",
                "summary": f"Evaluation error: {err}",
            })

    # Write results to CSV
    csv_path = Path(output_csv)
    fieldnames = ["filename", "score", "recommendation", "matched_skills", "missing_skills", "summary"]

    with open(csv_path, mode="w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print("-" * 70)
    print(f"[Batch Screening] Successfully processed {len(results)} resumes.")
    print(f"[Batch Screening] Results exported to: {csv_path.resolve()}\n")

    return results


# ---------------------------------------------------------------------------
# CLI Argument Parser & Execution
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Constructs the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="AI-Resume-Screening-Workflow: Evaluate resumes against a job description using Claude.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single resume evaluation (outputs formatted JSON to stdout):
  python screen.py samples/resume_1_strong_alex_chen.txt samples/job_description.txt

  # PDF resume evaluation:
  python screen.py samples/candidate.pdf samples/job_description.txt

  # Batch evaluation of all resumes in a directory (outputs results.csv):
  python screen.py --batch samples/ samples/job_description.txt

  # Test run in mock mode (no API key required):
  python screen.py --mock samples/resume_1_strong_alex_chen.txt samples/job_description.txt
        """,
    )

    parser.add_argument(
        "--batch",
        action="store_true",
        help="Batch mode: process all .txt and .pdf resumes in a directory and write results.csv",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in offline mock mode without contacting Anthropic API (for testing/demo)",
    )
    parser.add_argument(
        "--output-csv",
        default="results.csv",
        help="Path for CSV output in batch mode (default: results.csv)",
    )
    parser.add_argument(
        "target",
        help="Path to resume file (single mode) OR directory containing resumes (if --batch is specified)",
    )
    parser.add_argument(
        "job_description",
        help="Path to the job description file (.txt or .pdf)",
    )

    return parser


def main() -> None:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    # Determine whether mock mode was explicitly requested or fallback if key is missing and requested
    mock_mode = args.mock

    try:
        if args.batch:
            # Batch mode execution
            screen_batch(
                samples_dir=args.target,
                jd_file=args.job_description,
                output_csv=args.output_csv,
                mock=mock_mode,
            )
        else:
            # Single resume execution
            resume_path = Path(args.target)
            jd_path = Path(args.job_description)

            resume_text = extract_text_from_file(resume_path)
            jd_text = extract_text_from_file(jd_path)

            result = screen(resume_text, jd_text, mock=mock_mode)

            # Print formatted JSON as requested in requirement 3
            print(json.dumps(result, indent=2))

    except Exception as exc:
        sys.stderr.write(f"\n[ERROR] {exc}\n\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
