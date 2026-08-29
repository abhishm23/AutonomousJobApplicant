"""Evaluate how well a job description matches a resume."""

import os
import re


def evaluate_job(job_description, resume_text):
    """Return (score: int, reasoning: str) for how well the job fits the resume."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if api_key:
        return _evaluate_with_gemini(api_key, job_description, resume_text)
    return _evaluate_with_keywords(job_description, resume_text)


def _evaluate_with_gemini(api_key, job_description, resume_text):
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = f"""Evaluate how well this job description matches this resume.
Return ONLY a JSON object with two keys:
- "score": an integer 0-100 (100 = perfect match)
- "reasoning": a brief explanation (1-2 sentences)

Job Description:
{job_description[:3000]}

Resume:
{str(resume_text)[:3000]}"""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        import json
        match = re.search(r'\{[^}]+\}', text, re.DOTALL)
        if match:
            result = json.loads(match.group())
            score = max(0, min(100, int(result.get("score", 0))))
            reasoning = result.get("reasoning", "")
            return score, reasoning
    except Exception as e:
        print(f"  Gemini evaluation failed, using keyword fallback: {e}")

    return _evaluate_with_keywords(job_description, resume_text)


def _evaluate_with_keywords(job_description, resume_text):
    """Keyword-based scoring when no API key is available."""
    job_lower = job_description.lower()
    resume_lower = str(resume_text).lower() if resume_text else ""

    skill_patterns = [
        r'python', r'javascript', r'typescript', r'react', r'node\.?js',
        r'data science', r'machine learning', r'deep learning', r'artificial intelligence',
        r'aws', r'azure', r'gcp', r'docker', r'kubernetes', r'terraform',
        r'sql', r'nosql', r'mongodb', r'postgresql', r'mysql',
        r'api', r'rest', r'graphql', r'grpc',
        r'ci/cd', r'devops', r'agile', r'scrum',
        r'git', r'linux', r'bash', r'powershell',
        r'pandas', r'numpy', r'scikit', r'tensorflow', r'pytorch',
        r'excel', r'tableau', r'power bi',
        r'automation', r'scripting', r'etl',
        r'java', r'c\+\+', r'go', r'rust', r'scala', r'r\b',
        r'html', r'css', r'redis', r'kafka',
        r'cloud', r'infrastructure', r'monitoring', r'logging',
    ]

    resume_skills = set()
    for pattern in skill_patterns:
        if re.search(pattern, resume_lower):
            resume_skills.add(pattern.replace(r'\b', '').replace('\\', ''))

    if not resume_skills:
        words = set(re.findall(r'\b[a-zA-Z]{3,}\b', resume_lower))
        resume_skills = words

    matches = sum(1 for skill in resume_skills if skill.lower() in job_lower)
    total = max(len(resume_skills), 1)
    score = min(100, int((matches / total) * 100))

    matched = [s for s in resume_skills if s.lower() in job_lower]
    reasoning = (
        f"Matched {matches}/{total} skills. Found: {', '.join(matched[:8])}" if matched else
        f"No direct skill matches found in job description."
    )

    return score, reasoning
