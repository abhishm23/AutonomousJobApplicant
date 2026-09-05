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


CANONICAL_SKILL_PATTERNS = [
    ("Python", r"\bpython\b"),
    ("JavaScript", r"\bjavascript\b"),
    ("TypeScript", r"\btypescript\b"),
    ("React", r"\breact(?:\.js)?\b"),
    ("Node.js", r"\bnode(?:\.js)?\b"),
    ("Data Science", r"\bdata\s+science\b"),
    ("Machine Learning", r"\bmachine\s+learning\b"),
    ("Deep Learning", r"\bdeep\s+learning\b"),
    ("Artificial Intelligence", r"\bartificial\s+intelligence\b"),
    ("FastAPI", r"\bfastapi\b"),
    ("Django", r"\bdjango\b"),
    ("Flask", r"\bflask\b"),
    ("AWS", r"\baws\b"),
    ("Azure", r"\bazure\b"),
    ("GCP", r"\bgcp\b"),
    ("Docker", r"\bdocker\b"),
    ("Kubernetes", r"\bkubernetes\b"),
    ("Terraform", r"\bterraform\b"),
    ("SQL", r"\bsql\b"),
    ("NoSQL", r"\bnosql\b"),
    ("MongoDB", r"\bmongodb\b"),
    ("PostgreSQL", r"\bpostgresql\b"),
    ("MySQL", r"\bmysql\b"),
    ("API", r"\bapi\b"),
    ("REST", r"\brest(?:ful)?\b"),
    ("GraphQL", r"\bgraphql\b"),
    ("gRPC", r"\bgrpc\b"),
    ("CI/CD", r"\bci/cd\b"),
    ("DevOps", r"\bdevops\b"),
    ("Agile", r"\bagile\b"),
    ("Scrum", r"\bscrum\b"),
    ("Git", r"\bgit\b"),
    ("Linux", r"\blinux\b"),
    ("Bash", r"\bbash\b"),
    ("PowerShell", r"\bpowershell\b"),
    ("Pandas", r"\bpandas\b"),
    ("NumPy", r"\bnumpy\b"),
    ("Scikit-Learn", r"\bscikit(?:-learn)?\b"),
    ("TensorFlow", r"\btensorflow\b"),
    ("PyTorch", r"\bpytorch\b"),
    ("Excel", r"\bexcel\b"),
    ("Tableau", r"\btableau\b"),
    ("Power BI", r"\bpower\s*bi\b"),
    ("Automation", r"\bautomation\b"),
    ("Scripting", r"\bscripting\b"),
    ("ETL", r"\betl\b"),
    ("Java", r"\bjava\b"),
    ("C++", r"\bc\+\+\b"),
    ("C", r"\bc\b"),
    ("Go", r"\b(?:golang|go)\b"),
    ("Rust", r"\brust\b"),
    ("Scala", r"\bscala\b"),
    ("R", r"\br\b"),
    ("HTML", r"\bhtml\b"),
    ("CSS", r"\bcss\b"),
    ("Redis", r"\bredis\b"),
    ("Kafka", r"\bkafka\b"),
    ("Airflow", r"\bairflow\b"),
    ("Spark", r"\bspark\b"),
    ("Cloud", r"\bcloud\b"),
    ("Infrastructure", r"\binfrastructure\b"),
    ("Monitoring", r"\bmonitoring\b"),
    ("Logging", r"\blogging\b"),
]


def _evaluate_with_keywords(job_description, resume_text):
    """Keyword-based scoring when no API key is available with strict word-boundary matching."""
    job_str = str(job_description or "")
    resume_str = str(resume_text or "")

    if not job_str.strip() or not resume_str.strip():
        return 0, "No content provided to evaluate."

    # Extract required skills mentioned in the job description
    job_skills = []
    for skill_name, pattern in CANONICAL_SKILL_PATTERNS:
        if re.search(pattern, job_str, re.IGNORECASE):
            job_skills.append((skill_name, pattern))

    if job_skills:
        matched = []
        for skill_name, pattern in job_skills:
            if re.search(pattern, resume_str, re.IGNORECASE):
                matched.append(skill_name)

        matches = len(matched)
        total = len(job_skills)
        score = min(100, int((matches / total) * 100))

        reasoning = (
            f"Matched {matches}/{total} required skills. Found: {', '.join(matched[:8])}"
            if matched
            else f"Matched 0/{total} required skills ({', '.join([s[0] for s in job_skills[:5]])})."
        )
        return score, reasoning

    # Fallback to general vocabulary tokens in job description if no canonical skills found
    tokens = set(re.findall(r"\b[a-zA-Z]{3,}\b", job_str.lower()))
    stop_words = {
        "and", "the", "for", "with", "from", "that", "this", "have",
        "been", "were", "what", "when", "where", "which", "your",
        "their", "about", "into", "over", "after", "looking", "seeking",
        "role", "position", "team", "work", "experience", "years"
    }
    job_tokens = [w for w in tokens if w not in stop_words]

    if not job_tokens:
        return 0, "No recognizable skill keywords found in job description."

    matched_tokens = []
    for word in job_tokens:
        if re.search(rf"\b{re.escape(word)}\b", resume_str, re.IGNORECASE):
            matched_tokens.append(word)

    matches = len(matched_tokens)
    total = len(job_tokens)
    score = min(100, int((matches / total) * 100))

    reasoning = (
        f"Matched {matches}/{total} general keywords. Found: {', '.join(matched_tokens[:8])}"
        if matched_tokens
        else "No direct keyword matches found in resume."
    )

    return score, reasoning
