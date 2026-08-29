"""Parse PDF and JSON resumes into structured data."""

import json
import os
import re
import tempfile


SECTION_HEADERS = [
    "professional experience", "work experience", "experience",
    "technical experience", "career history", "employment",
    "education", "academic background",
    "skills", "technical skills", "core technical skills",
    "technical expertise", "proficiencies", "competencies",
    "summary", "professional summary", "profile",
    "objective", "about", "about me", "overview",
    "certifications", "certificates", "licenses",
    "projects", "personal projects", "side projects",
    "publications", "awards", "languages", "interests",
    "references", "volunteer",
]


def extract_text_from_pdf(pdf_path):
    """Extract raw text from a PDF file path."""
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def extract_resume_from_upload(uploaded_file):
    """Extract structured resume data from a PDF or JSON upload."""
    filename = uploaded_file.name if hasattr(uploaded_file, "name") else str(uploaded_file)
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".json":
        return _parse_json_upload(uploaded_file)
    elif ext == ".pdf":
        return _parse_pdf_upload(uploaded_file)
    else:
        return _parse_text_upload(uploaded_file)


def _parse_json_upload(uploaded_file):
    content = uploaded_file.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    try:
        data = json.loads(content)
        return {"format": "json", "text": content, "data": data}
    except json.JSONDecodeError:
        return {"format": "json", "text": content, "data": {}}


def _parse_pdf_upload(uploaded_file):
    try:
        import pdfplumber
        content = uploaded_file.read()
        if isinstance(content, bytes):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                with pdfplumber.open(tmp_path) as pdf:
                    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            finally:
                os.unlink(tmp_path)
        else:
            with pdfplumber.open(uploaded_file) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        if not text.strip():
            return _basic_structure_from_text("")
        return _basic_structure_from_text(text)
    except ImportError:
        return _basic_structure_from_text("")
    except Exception:
        return _basic_structure_from_text("")


def _parse_text_upload(uploaded_file):
    content = uploaded_file.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    return _basic_structure_from_text(content)


def _split_into_sections(text):
    sections = {}
    lines = text.split("\n")
    current_section = "header"
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            current_lines.append("")
            continue
        lower = stripped.lower().rstrip(":")
        is_header = False
        for header in SECTION_HEADERS:
            if lower == header or lower == header + ":":
                if current_lines:
                    sections[current_section] = "\n".join(current_lines).strip()
                current_section = header
                current_lines = []
                is_header = True
                break
        if not is_header:
            current_lines.append(stripped)

    if current_lines:
        sections[current_section] = "\n".join(current_lines).strip()
    return sections


def _basic_structure_from_text(text):
    """Extract structured resume data from plain text.

    Returns dict with keys: personal_info, experience, skills, education, summary, certifications.
    """
    sections = _split_into_sections(text)

    result = {
        "personal_info": {},
        "experience": [],
        "skills": [],
        "education": "",
        "summary": "",
        "certifications": [],
    }

    # Extract name
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and len(stripped) < 60 and not re.match(r'.+@.+', stripped):
            result["personal_info"]["name"] = stripped
            break

    # Extract email
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
    if email_match:
        result["personal_info"]["email"] = email_match.group(0)

    # Extract experience
    exp_text = (
        sections.get("professional experience")
        or sections.get("work experience")
        or sections.get("experience")
        or sections.get("technical experience")
        or sections.get("career history")
        or sections.get("employment")
    )
    if exp_text:
        result["experience"] = _parse_experience(exp_text)

    # Extract skills
    skills_text = (
        sections.get("skills")
        or sections.get("technical skills")
        or sections.get("core technical skills")
        or sections.get("technical expertise")
        or sections.get("proficiencies")
        or sections.get("competencies")
    )
    if skills_text:
        result["skills"] = _parse_skills(skills_text)

    # Extract education
    edu_text = sections.get("education") or sections.get("academic background")
    if edu_text:
        result["education"] = edu_text.strip()

    # Extract summary
    summary_text = (
        sections.get("summary")
        or sections.get("professional summary")
        or sections.get("profile")
        or sections.get("objective")
        or sections.get("about")
        or sections.get("about me")
        or sections.get("overview")
    )
    if summary_text:
        result["summary"] = summary_text.strip()

    # Extract certifications
    cert_text = (
        sections.get("certifications")
        or sections.get("certificates")
        or sections.get("licenses")
    )
    if cert_text:
        result["certifications"] = _parse_skills(cert_text)

    return result


def _parse_experience(text):
    """Parse experience section. Handles pipe-delimited and traditional formats."""
    entries = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            company = parts[0] if len(parts) > 0 else ""
            role = parts[1] if len(parts) > 1 else ""
            dates = parts[2] if len(parts) > 2 else ""
            location = parts[3] if len(parts) > 3 else ""
            bullets = []
            i += 1
            while i < len(lines):
                bline = lines[i].strip()
                if not bline:
                    i += 1
                    continue
                if "|" in bline or (bline.isupper() and len(bline) > 5):
                    break
                bline = re.sub(r'^[\-•\*\·]+\s*', '', bline)
                if bline:
                    bullets.append(bline)
                i += 1
            entries.append({
                "company": company, "role": role, "dates": dates,
                "location": location, "bullets": bullets,
            })
            continue

        company = line
        role = ""
        dates = ""
        location = ""
        bullets = []
        i += 1
        if i < len(lines):
            next_line = lines[i].strip()
            if next_line and not next_line.isupper():
                role = next_line
                i += 1
        while i < len(lines):
            bline = lines[i].strip()
            if not bline:
                i += 1
                continue
            if bline.isupper() and len(bline) > 5:
                break
            bline = re.sub(r'^[\-•\*\·]+\s*', '', bline)
            if bline:
                bullets.append(bline)
            i += 1
        if company:
            entries.append({
                "company": company, "role": role, "dates": dates,
                "location": location, "bullets": bullets,
            })

    return entries


def _parse_skills(text):
    """Parse skills section into a list."""
    skills = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        line = re.sub(r'^[\-•\*\·]+\s*', '', line)
        for part in re.split(r'[,;|·]', line):
            part = part.strip()
            if part and len(part) < 50:
                skills.append(part)
    return skills
