"""Generate HTML resume from structured data."""


class ResumeGenerator:
    TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} - Resume</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #333; line-height: 1.6; max-width: 800px; }}
  h1 {{ color: #1a1a2e; border-bottom: 3px solid #16213e; padding-bottom: 8px; }}
  h2 {{ color: #16213e; margin-top: 24px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  .contact {{ color: #555; margin-bottom: 20px; }}
  .experience {{ margin-bottom: 16px; }}
  .experience h3 {{ margin-bottom: 4px; color: #1a1a2e; }}
  .experience .meta {{ color: #666; font-style: italic; margin-bottom: 6px; }}
  ul {{ padding-left: 20px; }}
  li {{ margin-bottom: 4px; }}
  .skills {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .skill {{ background: #e8eaf6; padding: 4px 12px; border-radius: 12px; font-size: 0.9em; }}
</style>
</head>
<body>
<h1>{name}</h1>
<div class="contact">{contact}</div>
{summary_html}
{experience_html}
{skills_html}
{education_html}
</body>
</html>"""

    def generate(self, resume_data):
        if isinstance(resume_data, str):
            import json
            try:
                resume_data = json.loads(resume_data)
            except json.JSONDecodeError:
                return f"<html><body><pre>{resume_data}</pre></body></html>"

        name = resume_data.get("name", "Resume")
        email = resume_data.get("email", "")
        phone = resume_data.get("phone", "")
        contact = " · ".join(p for p in [email, phone] if p)

        summary = resume_data.get("summary", "")
        summary_html = f"<h2>Summary</h2><p>{summary}</p>" if summary else ""

        experience = resume_data.get("experience", [])
        exp_html = ""
        if experience:
            exp_html = "<h2>Experience</h2>\n"
            for exp in experience:
                if isinstance(exp, dict):
                    company = exp.get("company", "")
                    role = exp.get("role", "")
                    dates = exp.get("dates", "")
                    location = exp.get("location", "")
                    header = f"{role}" + (f" at {company}" if company else "")
                    meta = " · ".join(p for p in [dates, location] if p)
                    exp_html += f'<div class="experience">\n'
                    exp_html += f"  <h3>{header}</h3>\n"
                    if meta:
                        exp_html += f'  <div class="meta">{meta}</div>\n'
                    bullets = exp.get("bullets", [])
                    if bullets:
                        exp_html += "  <ul>\n"
                        for b in bullets:
                            exp_html += f"    <li>{b}</li>\n"
                        exp_html += "  </ul>\n"
                    exp_html += "</div>\n"

        skills = resume_data.get("skills", [])
        skills_html = ""
        if skills:
            if isinstance(skills, list):
                skill_items = "".join(f'<span class="skill">{s}</span>' for s in skills)
            else:
                skill_items = f'<span class="skill">{skills}</span>'
            skills_html = f'<h2>Skills</h2>\n<div class="skills">{skill_items}</div>'

        education = resume_data.get("education", "")
        education_html = f"<h2>Education</h2><p>{education}</p>" if education else ""

        return self.TEMPLATE.format(
            name=name, contact=contact, summary_html=summary_html,
            experience_html=exp_html, skills_html=skills_html, education_html=education_html,
        )
