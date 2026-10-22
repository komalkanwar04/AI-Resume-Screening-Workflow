"""
Utility script to generate a sample PDF resume for testing PDF text extraction.
Uses standard PDF 1.4 syntax to generate samples/resume_1_strong_alex_chen.pdf.
"""
from pathlib import Path

def create_pdf(output_path: Path):
    lines = [
        "ALEX CHEN",
        "San Francisco, CA | alex.chen.fake@example.com",
        "OBJECTIVE: AI Engineering Intern focused on automation and LLM pipelines.",
        "EDUCATION: UC Berkeley, B.S. in Computer Science (Expected May 2026)",
        "SKILLS: Python, Anthropic Claude API, Prompt Engineering, n8n, Webhooks, REST APIs, pypdf, Git",
        "EXPERIENCE:",
        "- Built AI resume screening prototype with Claude API and n8n webhook triggers.",
        "- Implemented Python pipelines for structured JSON outputs and automated evaluation.",
        "- Integrated REST APIs with error handling and rate-limit backoff."
    ]

    # Format text for PDF stream
    text_stream_parts = ["BT", "/F1 11 Tf", "50 720 Td", "16 TL"]
    for i, line in enumerate(lines):
        # Escape parentheses and backslashes for PDF literal strings
        safe_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if i == 0:
            text_stream_parts.append(f"({safe_line}) Tj")
        else:
            text_stream_parts.append(f"T* ({safe_line}) Tj")
    text_stream_parts.append("ET")
    stream_content = "\n".join(text_stream_parts).encode("latin-1")
    stream_len = len(stream_content)

    # Assemble PDF objects
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
    )
    obj4 = b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    obj5 = f"5 0 obj\n<< /Length {stream_len} >>\nstream\n".encode("latin-1") + stream_content + b"\nendstream\nendobj\n"

    header = b"%PDF-1.4\n"
    offset1 = len(header)
    offset2 = offset1 + len(obj1)
    offset3 = offset2 + len(obj2)
    offset4 = offset3 + len(obj3)
    offset5 = offset4 + len(obj4)
    xref_offset = offset5 + len(obj5)

    xref = (
        f"xref\n0 6\n"
        f"0000000000 65535 f \n"
        f"{offset1:010d} 00000 n \n"
        f"{offset2:010d} 00000 n \n"
        f"{offset3:010d} 00000 n \n"
        f"{offset4:010d} 00000 n \n"
        f"{offset5:010d} 00000 n \n"
        f"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("latin-1")

    full_pdf = header + obj1 + obj2 + obj3 + obj4 + obj5 + xref
    with open(output_path, "wb") as f:
        f.write(full_pdf)

if __name__ == "__main__":
    out = Path("samples/resume_1_strong_alex_chen.pdf")
    create_pdf(out)
    print(f"Created sample PDF at: {out}")
