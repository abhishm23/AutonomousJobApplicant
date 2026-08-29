"""Job Finder Dashboard — Streamlit UI for the autonomous job applicant pipeline."""

import html
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from db.database import Database
from orchestrator import run_pipeline


# ─── Page Config ──────────────────────────────────────────────────────
st.set_page_config(page_title="Job Finder", page_icon="🎯", layout="wide")

st.markdown("""
<style>
  .job-card { background: #1e1e2e; border: 1px solid #313244; border-radius: 10px; padding: 16px; margin-bottom: 12px; }
  .job-title { font-size: 1.1em; font-weight: 600; color: #cdd6f4; }
  .job-company { color: #a6adc8; margin: 4px 0 8px; }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.8em; font-weight: 600; margin-right: 6px; }
  .score-badge { background: #a6e3a1; color: #1e1e2e; }
  .salary-badge { background: #f9e2af; color: #1e1e2e; }
  .source-badge { background: #89b4fa; color: #1e1e2e; }
  .stMetric > div { background: #1e1e2e; border-radius: 10px; padding: 12px; }
</style>
""", unsafe_allow_html=True)


# ─── Session State ────────────────────────────────────────────────────
if "resume_data" not in st.session_state:
    st.session_state.resume_data = None
if "resume_text" not in st.session_state:
    st.session_state.resume_text = ""
if "keywords" not in st.session_state:
    st.session_state.keywords = ""
if "pipeline_done" not in st.session_state:
    st.session_state.pipeline_done = False
if "min_score" not in st.session_state:
    st.session_state.min_score = 70


# ─── Step 1: Upload Resume ───────────────────────────────────────────
st.header("📋 Step 1: Upload Resume")
uploaded = st.file_uploader("Upload your resume (PDF or JSON)", type=["pdf", "json"])

if uploaded:
    from resume_engine.resume_parser import extract_resume_from_upload
    if st.session_state.resume_data is None:
        st.session_state.resume_data = extract_resume_from_upload(uploaded)
        if st.session_state.resume_data:
            st.session_state.resume_text = str(st.session_state.resume_data)
            st.success(f"✅ Parsed: {uploaded.name}")

if st.session_state.resume_data:
    with st.expander("📄 Parsed Resume Preview", expanded=False):
        st.json(st.session_state.resume_data)


# ─── Step 2: Enter Keywords ──────────────────────────────────────────
st.header("🔍 Step 2: Search Keywords")
keywords = st.text_input(
    "Job keywords (comma-separated)",
    placeholder="python, data scientist, remote",
    value=st.session_state.keywords,
)
st.session_state.keywords = keywords

min_score = st.slider("Minimum match score", 0, 100, st.session_state.min_score)
st.session_state.min_score = min_score


# ─── Step 3: Find Jobs ───────────────────────────────────────────────
st.header("🚀 Step 3: Find Jobs")

col1, col2 = st.columns([1, 3])
with col1:
    find_btn = st.button("Find Jobs", type="primary", disabled=not uploaded)

if find_btn and keywords:
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keyword_list:
        st.warning("Enter at least one keyword.")
    else:
        progress = st.empty()
        status = st.empty()

        def update_progress(msg):
            progress.caption(msg)

        with st.spinner("Running pipeline..."):
            result = run_pipeline(
                resume_text=st.session_state.resume_text,
                keywords=keyword_list,
                min_score=min_score,
                progress_callback=update_progress,
            )

        progress.empty()
        status.success(
            f"✅ Found {result['total_scraped']} jobs · "
            f"{result['evaluated']} evaluated · "
            f"{result['ready']} ready to apply"
        )
        st.session_state.pipeline_done = True


# ─── Results ──────────────────────────────────────────────────────────
if st.session_state.pipeline_done or uploaded:
    st.header("📊 Results")

    db = Database()
    try:
        apps_df = db.get_ready_applications()
        all_jobs_df = db.get_all_jobs()
    finally:
        db.close()

    if all_jobs_df.empty and apps_df.empty:
        st.info("No jobs found yet. Upload your resume and click **Find Jobs**.")
    else:
        total = len(all_jobs_df)
        ready = len(apps_df) if not apps_df.empty else 0
        applied_count = 0
        if not apps_df.empty:
            applied_count = int((apps_df["app_status"] == "applied").sum())

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Scraped", total)
        m2.metric("Ready", ready)
        m3.metric("Applied", applied_count)

        tab_ready, tab_applied, tab_all = st.tabs(["🎯 Ready to Apply", "✅ Applied", "📋 All Jobs"])

        with tab_ready:
            if apps_df.empty:
                st.info("No ready applications. Run the pipeline first.")
            else:
                for _, row in apps_df.iterrows():
                    if row["app_status"] != "ready":
                        continue
                    score = int(row["match_score"]) if row["match_score"] and not (isinstance(row["match_score"], float) and math.isnan(row["match_score"])) else 0
                    reasoning = html.escape(str(row.get("match_reasoning", "") or ""))
                    company = html.escape(str(row["company"]))
                    title = html.escape(str(row["title"]))
                    salary = html.escape(str(row["salary_range"] or "Not specified"))
                    url = html.escape(str(row["url"] or "#"))

                    st.markdown(f"""
                    <div class="job-card">
                        <div class="job-title">{title}</div>
                        <div class="job-company">{company}</div>
                        <div>
                            <span class="badge score-badge">Match: {score}%</span>
                            <span class="badge salary-badge">{salary}</span>
                        </div>
                        <p style="font-size:0.85em; color:#a6adc8; margin-top:8px;">{reasoning}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    st.link_button("🔗 Apply Now", url)
                    st.divider()

        with tab_applied:
            if apps_df.empty:
                st.info("No applications yet.")
            else:
                applied_df = apps_df[apps_df["app_status"] == "applied"]
                if applied_df.empty:
                    st.info("No applications marked as applied yet.")
                else:
                    for _, row in applied_df.iterrows():
                        score = int(row["match_score"]) if row["match_score"] and not (isinstance(row["match_score"], float) and math.isnan(row["match_score"])) else 0
                        company = html.escape(str(row["company"]))
                        title = html.escape(str(row["title"]))
                        url = html.escape(str(row["url"] or "#"))

                        st.markdown(f"""
                        <div class="job-card">
                            <div class="job-title">{title}</div>
                            <div class="job-company">{company}</div>
                            <span class="badge score-badge">Match: {score}%</span>
                        </div>
                        """, unsafe_allow_html=True)
                        st.link_button("🔗 View", url)
                        st.divider()

        with tab_all:
            if all_jobs_df.empty:
                st.info("No jobs in database.")
            else:
                for _, row in all_jobs_df.iterrows():
                    score = int(row["match_score"]) if row["match_score"] and not (isinstance(row["match_score"], float) and math.isnan(row["match_score"])) else None
                    score_text = f"Match: {score}%" if score is not None else "Not evaluated"
                    company = html.escape(str(row["company"]))
                    title = html.escape(str(row["title"]))
                    salary = html.escape(str(row["salary_range"] or "Not specified"))
                    source = html.escape(str(row["platform"]))
                    url = html.escape(str(row["url"] or "#"))

                    st.markdown(f"""
                    <div class="job-card">
                        <div class="job-title">{title}</div>
                        <div class="job-company">{company} · {source}</div>
                        <div>
                            <span class="badge source-badge">{source}</span>
                            <span class="badge salary-badge">{salary}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    st.link_button("🔗 View Job", url)
                    st.divider()

    st.caption("Built with ❤️ using Streamlit · Scrapers: RemoteOK, WeWorkRemotely, Remotive, Himalayas")
