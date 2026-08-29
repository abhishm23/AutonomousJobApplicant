"""
Behavioral contract for Remote Job Finder changes.
Tests the smallest set of behaviors that define correctness.
"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scraper.multi_scraper import scrape_all
from db.database import Database
from resume_engine.resume_parser import (
    extract_resume_from_upload, extract_text_from_pdf,
    _basic_structure_from_text, _parse_experience,
)

PASS = FAIL = 0
def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1; print(f"  ✓ {name}")
    else:
        FAIL += 1; print(f"  ✗ {name}: {detail}")


# ── 1. Scraping ──────────────────────────────────────────────
print("\n=== Scraping ===")
jobs = scrape_all(['python'], limit_per_source=1)
check("scrape_all returns list of dicts with required keys",
      jobs and all(k in jobs[0] for k in ("title", "company", "url", "platform")))
check("scrape_all deduplicates",
      len(jobs) == len({(j["title"].lower(), j["company"].lower()) for j in jobs}))


# ── 2. Database ──────────────────────────────────────────────
print("\n=== Database ===")
tmp = os.path.join(tempfile.gettempdir(), f"contract_{os.getpid()}.duckdb")
db = Database(db_path=tmp)

jid1 = db.insert_job("src", "1", "Job A", "Co", "", "", "", "", "")
jid2 = db.insert_job("src", "1", "Job B", "Co2", "", "", "", "", "")  # same key
jid3 = db.insert_job("src", "2", "Job C", "Co3", "", "", "", "", "")  # new key
check("insert_job returns id", jid1 is not None)
check("insert_job deduplicates on (platform, job_id)", jid1 == jid2)
check("insert_job allows different keys", jid3 != jid1)

db.update_job_match(jid1, 85, "Strong Python match")
df = db.get_all_jobs()
row = df[df["id"] == jid1].iloc[0]
check("update_job_match stores score", int(row["match_score"]) == 85)
check("update_job_match stores reasoning", row["match_reasoning"] == "Strong Python match")
check("update_job_match sets status to evaluated", row["status"] == "evaluated")

uneval = db.get_unevaluated_jobs()
check("get_unevaluated_jobs returns only scraped jobs",
      len(uneval) == 1 and uneval[0][0] == jid3)
check("get_ready_applications returns empty when no apps",
      db.get_ready_applications().empty)

db.close(); os.unlink(tmp)


# ── 3. Resume parsing ────────────────────────────────────────
print("\n=== Resume parsing ===")

# Pipe-delimited experience
exp_text = "Acme Corp | Software Engineer | Jan 2020 – Present\n• Built thing\n• Shipped thing"
entries = _parse_experience(exp_text)
check("pipe-delimited experience: company", entries[0]["company"] == "Acme Corp")
check("pipe-delimited experience: dates", "2020" in entries[0]["dates"])
check("pipe-delimited experience: bullets", len(entries[0]["bullets"]) == 2)

# Empty/edge inputs
check("empty experience returns []", _parse_experience("") == [])
check("empty text returns valid structure", isinstance(_basic_structure_from_text(""), dict))

# Name + email extraction
r = _basic_structure_from_text("Jane Doe\njane@example.com")
check("name extracted from first line", r["personal_info"]["name"] == "Jane Doe")
check("email extracted", r["personal_info"]["email"] == "jane@example.com")

# Upload handling
class FakeFile:
    name = "resume.json"
    def read(self):
        return json.dumps({"personal_info": {"name": "X"}}).encode()
result = extract_resume_from_upload(FakeFile())
check("JSON upload returns parsed json", result["format"] == "json" and json.loads(result["text"]))

# Real PDF
pdf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Abhishek_Mishra_Resume.pdf")
if os.path.exists(pdf_path):
    parsed = _basic_structure_from_text(extract_text_from_pdf(pdf_path))
    check("PDF: name extracted", bool(parsed["personal_info"]["name"]))
    check("PDF: email extracted", bool(parsed["personal_info"]["email"]))
    check("PDF: experience parsed", len(parsed["experience"]) > 0)
    check("PDF: certifications parsed", len(parsed["certifications"]) > 0)


# ── 4. Interface contracts ───────────────────────────────────
print("\n=== Interface contracts ===")
import inspect, py_compile

from orchestrator import run_pipeline
sig = inspect.signature(run_pipeline)
params = list(sig.parameters.keys())
check("run_pipeline accepts (resume_text, resume_json, keywords, min_score, progress_callback)",
      params == ["resume_text", "resume_json", "keywords", "min_score", "progress_callback"])

check("dashboard/app.py compiles", py_compile.compile("dashboard/app.py", doraise=True) is not None)


# ── Summary ──────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL}")
if FAIL == 0:
    print("ALL TESTS PASSED")
else:
    print(f"WARNING: {FAIL} FAILURES")
