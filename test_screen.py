"""
Unit and integration tests for AI-Resume-Screening-Workflow (screen.py).
Tests:
1. extract_text_from_file on .txt files and .pdf files
2. parse_and_validate_json schema validation and edge cases
3. screen() in mock mode
4. Batch execution and CSV writing
5. Error handling (missing files, malformed JSON, invalid score/recommendations)
"""

import json
import os
import unittest
from pathlib import Path
from screen import (
    extract_text_from_file,
    parse_and_validate_json,
    screen,
    screen_batch,
    REQUIRED_KEYS,
    VALID_RECOMMENDATIONS,
)


class TestResumeScreening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples_dir = Path("samples")
        cls.jd_file = cls.samples_dir / "job_description.txt"
        cls.alex_txt = cls.samples_dir / "resume_1_strong_alex_chen.txt"
        cls.alex_pdf = cls.samples_dir / "pdf_test" / "resume_1_strong_alex_chen.pdf"
        cls.jordan_txt = cls.samples_dir / "resume_2_average_jordan_taylor.txt"
        cls.samira_txt = cls.samples_dir / "resume_3_average_samira_khan.txt"
        cls.morgan_txt = cls.samples_dir / "resume_4_weak_morgan_reed.txt"

    def test_sample_files_exist(self):
        """Verify all 4 sample resumes and the JD exist."""
        self.assertTrue(self.jd_file.exists())
        self.assertTrue(self.alex_txt.exists())
        self.assertTrue(self.jordan_txt.exists())
        self.assertTrue(self.samira_txt.exists())
        self.assertTrue(self.morgan_txt.exists())
        self.assertTrue(self.alex_pdf.exists())

    def test_extract_text_from_txt(self):
        """Verify text extraction from a UTF-8 text file."""
        text = extract_text_from_file(self.alex_txt)
        self.assertIn("ALEX CHEN", text)
        self.assertIn("Python", text)
        self.assertIn("Claude", text)

    def test_extract_text_from_pdf(self):
        """Verify text extraction from a PDF file using pypdf."""
        text = extract_text_from_file(self.alex_pdf)
        self.assertIn("ALEX CHEN", text)
        self.assertIn("Python", text)

    def test_extract_text_nonexistent_file(self):
        """Verify FileNotFoundError is raised for non-existent file."""
        with self.assertRaises(FileNotFoundError):
            extract_text_from_file("samples/does_not_exist.txt")

    def test_parse_valid_json_plain(self):
        """Verify parsing clean JSON string without code fences."""
        raw = json.dumps({
            "score": 85,
            "matched_skills": ["Python", "FastAPI"],
            "missing_skills": ["Docker"],
            "summary": "Solid candidate with good backend skills. Ready for interview.",
            "recommendation": "shortlist"
        })
        result = parse_and_validate_json(raw)
        self.assertEqual(result["score"], 85)
        self.assertEqual(result["recommendation"], "shortlist")
        self.assertEqual(len(result["matched_skills"]), 2)

    def test_parse_valid_json_with_code_fences(self):
        """Verify stripping of markdown ```json ... ``` code fences."""
        raw = """```json
{
  "score": 90,
  "matched_skills": ["Claude", "n8n"],
  "missing_skills": [],
  "summary": "Excellent fit for automation role. Highly recommended.",
  "recommendation": "shortlist"
}
```"""
        result = parse_and_validate_json(raw)
        self.assertEqual(result["score"], 90)
        self.assertEqual(result["recommendation"], "shortlist")

    def test_parse_missing_required_key(self):
        """Verify ValueError is raised when a required key is absent."""
        raw = json.dumps({
            "score": 70,
            "matched_skills": ["Python"],
            # missing missing_skills, summary, recommendation
        })
        with self.assertRaises(ValueError) as ctx:
            parse_and_validate_json(raw)
        self.assertIn("missing required keys", str(ctx.exception))

    def test_parse_invalid_score_range(self):
        """Verify ValueError on score out of 0-100 bounds."""
        raw = json.dumps({
            "score": 150,
            "matched_skills": [],
            "missing_skills": [],
            "summary": "Out of bounds.",
            "recommendation": "shortlist"
        })
        with self.assertRaises(ValueError) as ctx:
            parse_and_validate_json(raw)
        self.assertIn("between 0 and 100", str(ctx.exception))

    def test_parse_invalid_recommendation(self):
        """Verify ValueError on invalid recommendation string."""
        raw = json.dumps({
            "score": 50,
            "matched_skills": [],
            "missing_skills": [],
            "summary": "Average profile.",
            "recommendation": "hire_immediately"  # Invalid!
        })
        with self.assertRaises(ValueError) as ctx:
            parse_and_validate_json(raw)
        self.assertIn("must be one of", str(ctx.exception))

    def test_parse_malformed_json_syntax(self):
        """Verify ValueError on malformed JSON syntax."""
        raw = "{ score: 90, matched_skills: missing quotes }"
        with self.assertRaises(ValueError) as ctx:
            parse_and_validate_json(raw)
        self.assertIn("Failed to parse Claude output as JSON", str(ctx.exception))

    def test_screen_mock_strong_candidate(self):
        """Test mock screening on Alex Chen (strong match)."""
        resume_text = extract_text_from_file(self.alex_txt)
        jd_text = extract_text_from_file(self.jd_file)
        result = screen(resume_text, jd_text, mock=True)

        self.assertGreaterEqual(result["score"], 85)
        self.assertEqual(result["recommendation"], "shortlist")
        self.assertIn("Python programming", result["matched_skills"])

    def test_screen_mock_weak_candidate(self):
        """Test mock screening on Morgan Reed (weak match)."""
        resume_text = extract_text_from_file(self.morgan_txt)
        jd_text = extract_text_from_file(self.jd_file)
        result = screen(resume_text, jd_text, mock=True)

        self.assertLess(result["score"], 50)
        self.assertEqual(result["recommendation"], "reject")

    def test_batch_processing_and_csv(self):
        """Test batch mode on samples/ producing test_results.csv."""
        test_csv = Path("test_results.csv")
        try:
            results = screen_batch(
                samples_dir=self.samples_dir,
                jd_file=self.jd_file,
                output_csv=test_csv,
                mock=True,
            )
            self.assertTrue(test_csv.exists())
            self.assertEqual(len(results), 4)

            # Check that results.csv has valid columns
            with open(test_csv, "r", encoding="utf-8") as f:
                header = f.readline().strip()
                self.assertIn("filename,score,recommendation", header)
        finally:
            if test_csv.exists():
                test_csv.unlink()


if __name__ == "__main__":
    unittest.main()
