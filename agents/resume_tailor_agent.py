"""Tailor a resume to match a specific job description."""

import json
import os
import re


def tailor_resume(resume_data, job_description, job_title, company):
    """Return a tailored resume dict for the given job."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if api_key:
        return _tailor_with_gemini(api_key, resume_data, job_description, job_title, company)
    return _tailor_basic(resume_data, job_description, job_title, company)


def _tailor_with_gemini(api_key, resume_data, job_description, job_title, company):
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = f"""Tailor this resume for the following job. Return a JSON object matching this schema:
{{
  "name": "...",
  "email": "...",
  "summary": "A 2-3 sentence professional summary tailored to this role",
  "experience": [
    {{
      "company": "...",
      "role": "...",
      "dates": "...",
      "location": "...",
      "bullets": ["..."]
    }}
  ],
  "skills": ["..."],
  "education": "..."
}}

Job: {job_title} at {company}
Job Description: {job_description[:3000]}

Resume:
{str(resume_data)[:4000]}"""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"  Gemini tailoring failed, using basic: {e}")

    return _tailor_basic(resume_data, job_description, job_title, company)


def _tailor_basic(resume_data, job_description, job_title, company):
    """Basic tailoring without AI — highlight relevant experience."""
    if isinstance(resume_data, str):
        try:
            resume_data = json.loads(resume_data)
        except json.JSONDecodeError:
            return {"raw_text": resume_data, "summary": f"Applying for {job_title} at {company}"}

    tailored = dict(resume_data) if isinstance(resume_data, dict) else {"raw_text": str(resume_data)}
    tailored["summary"] = tailored.get("summary", "") or f"Experienced professional seeking {job_title} role at {company}."

    job_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', job_description.lower()))
    experience = tailored.get("experience", [])
    for exp in experience:
        if isinstance(exp, dict):
            bullets = exp.get("bullets", [])
            scored = []
            for b in bullets:
                b_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', b.lower()))
                overlap = len(b_words & job_words)
                scored.append((overlap, b))
            scored.sort(key=lambda x: -x[0])
            exp["bullets"] = [b for _, b in scored[:5]]
    tailored["experience"] = experience

    skills = tailored.get("skills", [])
    if isinstance(skills, list) and skills:
        relevant = [s for s in skills if s.lower() in job_description.lower() or any(
            w in s.lower() for w in job_words
        )]
        if relevant:
            tailored["skills"] = relevant

    return tailored
