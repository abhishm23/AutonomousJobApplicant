"""
Autonomous Job Applicant — Application Tracking Console & Dashboard.

Streamlit application providing:
1. Interactive 6-Stage Kanban Pipeline Board (Ready to Apply, Applied, Reply Received, Interview Scheduled, Rejected, Offer)
2. Filterable & Sortable Application Table with multi-field search and inline stage management
3. Recruiter notes, interview scheduling, and chronological audit history timeline
4. Persistent browser session manager & non-blocking login browser launcher in sidebar
5. Step-by-step pipeline runner, evaluation workbench, and job board explorer
"""

import html
import json
import logging
import math
import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import streamlit as st
from config import config
from db.database import Database
from orchestrator import run_pipeline
from utils.browser_manager import BrowserManager, DEFAULT_USER_DATA_DIR

logger = logging.getLogger(__name__)


# ─── Helper Functions & Constants ────────────────────────────────────
def clean_score(val: Any) -> Optional[int]:
    """Safely sanitize score values from DuckDB."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def get_score_badge_html(score: Optional[int]) -> str:
    """Returns styled HTML badge for match score."""
    if score is None:
        return '<span class="badge" style="background:#313244; color:#6c7086;">Unevaluated</span>'
    if score >= 80:
        cls = "badge-score-high"
    elif score >= 60:
        cls = "badge-score-mid"
    else:
        cls = "badge-score-low"
    return f'<span class="badge {cls}">Match: {score}%</span>'


def filter_applications(
    all_apps: List[Dict[str, Any]],
    search_query: str = "",
    selected_platforms: Optional[List[str]] = None,
    selected_stages: Optional[List[str]] = None,
    min_table_score: int = 0,
) -> List[Dict[str, Any]]:
    """
    Filter application records according to search query, platform, stage, and match score.
    Safely handles None and NaN match scores (excluding unevaluated when min_table_score > 0).
    """
    filtered = []
    for app in all_apps:
        # Platform filter
        p = str(app.get("platform") or "")
        if selected_platforms is not None and p not in selected_platforms:
            continue

        # Stage filter
        stg = str(app.get("app_status") or "Ready to Apply")
        if selected_stages is not None and stg not in selected_stages:
            continue

        # Score filter: treat None/NaN as unevaluated (0) when filtering by positive min score
        score = clean_score(app.get("match_score"))
        if min_table_score > 0 and (score is None or score < min_table_score):
            continue

        # Text search filter across title, company, skills, notes, reasoning
        if search_query and search_query.strip():
            sq = search_query.strip().lower()
            t = str(app.get("title") or "").lower()
            c = str(app.get("company") or "").lower()
            sk = str(app.get("skills") or "").lower()
            n = str(app.get("notes") or "").lower()
            mr = str(app.get("match_reasoning") or "").lower()
            if sq not in t and sq not in c and sq not in sk and sq not in n and sq not in mr:
                continue

        filtered.append(app)
    return filtered


STAGE_NEXT_MAP = {
    "Ready to Apply": "Applied",
    "Applied": "Reply Received",
    "Reply Received": "Interview Scheduled",
    "Interview Scheduled": "Offer",
    "Rejected": "Ready to Apply",
    "Offer": "Offer",
}

KANBAN_STAGES = [
    "Ready to Apply",
    "Applied",
    "Reply Received",
    "Interview Scheduled",
    "Rejected",
    "Offer",
]

CORE_PORTALS = ["LinkedIn", "Naukri", "Wellfound", "Hirist"]


def main():
    """Main Streamlit application entrypoint."""
    # ─── Page Configuration ──────────────────────────────────────────────
    st.set_page_config(
        page_title="Autonomous Job Applicant — Console",
        page_icon="💼",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ─── Custom Styles ───────────────────────────────────────────────────
    st.markdown("""
    <style>
      /* Global card & metric styles */
      .stMetric > div { background: #1e1e2e; border: 1px solid #313244; border-radius: 8px; padding: 10px 14px; }
      .kanban-col-header { font-weight: 700; font-size: 1.05rem; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; text-align: center; }
      .hdr-ready { background: #313244; color: #89b4fa; border-left: 4px solid #89b4fa; }
      .hdr-applied { background: #313244; color: #a6e3a1; border-left: 4px solid #a6e3a1; }
      .hdr-reply { background: #313244; color: #f9e2af; border-left: 4px solid #f9e2af; }
      .hdr-interview { background: #313244; color: #fab387; border-left: 4px solid #fab387; }
      .hdr-rejected { background: #313244; color: #f38ba8; border-left: 4px solid #f38ba8; }
      .hdr-offer { background: #313244; color: #cba6f7; border-left: 4px solid #cba6f7; }

      .job-card {
          background: #181825;
          border: 1px solid #313244;
          border-radius: 8px;
          padding: 12px 14px;
          margin-bottom: 12px;
          box-shadow: 0 2px 4px rgba(0,0,0,0.15);
      }
      .job-card:hover { border-color: #585b70; }
      .job-card-title { font-size: 0.95rem; font-weight: 600; color: #cdd6f4; line-height: 1.3; margin-bottom: 4px; }
      .job-card-company { font-size: 0.85rem; color: #a6adc8; margin-bottom: 8px; }
      .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.75rem; font-weight: 600; margin-right: 4px; margin-bottom: 4px; }
      .badge-platform { background: #313244; color: #89b4fa; border: 1px solid #45475a; }
      .badge-score-high { background: #1c3b2b; color: #a6e3a1; border: 1px solid #2d5a40; }
      .badge-score-mid { background: #3b351c; color: #f9e2af; border: 1px solid #5a502d; }
      .badge-score-low { background: #3b1c1c; color: #f38ba8; border: 1px solid #5a2d2d; }
      .badge-salary { background: #252438; color: #cba6f7; }
      .badge-location { background: #222533; color: #94e2d5; }
      .timeline-entry { border-left: 2px solid #585b70; padding-left: 10px; margin-bottom: 8px; font-size: 0.82rem; }
      .timeline-time { color: #6c7086; font-size: 0.75rem; }
      .timeline-note { color: #bac2de; }
    </style>
    """, unsafe_allow_html=True)

    # ─── Session State Initialization ────────────────────────────────────
    if "resume_data" not in st.session_state:
        st.session_state.resume_data = None
    if "resume_text" not in st.session_state:
        st.session_state.resume_text = ""
    if "keywords" not in st.session_state:
        st.session_state.keywords = getattr(config, "TARGET_ROLES", "Python Developer, Data Engineer")
    if "min_score" not in st.session_state:
        st.session_state.min_score = 70
    if "last_action_msg" not in st.session_state:
        st.session_state.last_action_msg = ""
    if "auth_launch_msg" not in st.session_state:
        st.session_state.auth_launch_msg = ""

    # ─── Sidebar: Session Management & Quick Controls ────────────────────
    with st.sidebar:
        st.title("💼 Job Applicant")
        st.caption("Autonomous Ingestion, Tracking & Tailoring")

        st.markdown("---")
        st.subheader("🔐 Browser Sessions")
        st.caption("Persistent authenticated sessions for direct scraping & auto-fill.")

        # Portal Session Status Indicators
        session_status = BrowserManager.get_session_status_all()
        for portal_key in ["linkedin", "naukri", "wellfound", "hirist"]:
            p_info = session_status.get(portal_key, {})
            has_sess = p_info.get("has_session", False)
            status_icon = "🟢" if has_sess else "⚪"
            status_text = "Authenticated" if has_sess else "Not Logged In"
            st.markdown(f"**{portal_key.capitalize()}**: {status_icon} `{status_text}`")

        selected_portal = st.selectbox(
            "Select Portal to Log In",
            options=["linkedin", "naukri", "wellfound", "hirist", "indeed"],
            format_func=lambda x: x.capitalize(),
        )

        if st.button("🚀 Launch Login Browser", use_container_width=True):
            try:
                # Non-blocking subprocess execution
                auth_script = os.path.join(PROJECT_ROOT, "auth_login.py")
                subprocess.Popen([sys.executable, auth_script, "--portal", selected_portal])
                st.session_state.auth_launch_msg = (
                    f"Launched browser for {selected_portal.capitalize()}! Complete login & OTP in the opened window."
                )
            except Exception as e:
                st.session_state.auth_launch_msg = f"Failed to launch browser: {e}"

        if st.session_state.auth_launch_msg:
            st.info(st.session_state.auth_launch_msg)

        if st.button("🔄 Refresh Session Status", use_container_width=True):
            st.session_state.auth_launch_msg = "Refreshed session status."
            st.rerun()

        st.markdown("---")
        st.subheader("📊 System Overview")
        with Database() as db:
            kanban_counts = db.get_kanban_applications()
            all_jobs_count = len(db.get_all_jobs())

        total_apps = sum(len(v) for v in kanban_counts.values())
        st.metric("Total Jobs Ingested", all_jobs_count)
        st.metric("Active Applications", total_apps)

    # ─── Top Metrics Bar ─────────────────────────────────────────────────
    st.title("💼 Application Tracking Console")

    with Database() as db:
        kanban_data = db.get_kanban_applications()
        all_jobs = db.get_all_jobs()
        all_apps = db.get_all_applications_table()

    col_m1, col_m2, col_m3, col_m4, col_m5, col_m6 = st.columns(6)
    col_m1.metric("🎯 Ready to Apply", len(kanban_data.get("Ready to Apply", [])))
    col_m2.metric("📤 Applied", len(kanban_data.get("Applied", [])))
    col_m3.metric("💬 Reply Received", len(kanban_data.get("Reply Received", [])))
    col_m4.metric("📅 Interviews", len(kanban_data.get("Interview Scheduled", [])))
    col_m5.metric("🚫 Rejected", len(kanban_data.get("Rejected", [])))
    col_m6.metric("🎉 Offers", len(kanban_data.get("Offer", [])))

    if st.session_state.last_action_msg:
        st.success(st.session_state.last_action_msg)
        st.session_state.last_action_msg = ""

    # ─── Main Tab Navigation ─────────────────────────────────────────────
    tab_kanban, tab_table, tab_ready, tab_explorer, tab_pipeline = st.tabs([
        "📊 Application Kanban",
        "📋 Applications Table",
        "🎯 Ready to Apply / Evaluation",
        "🔍 Job Board Explorer",
        "⚙️ Pipeline & Auth",
    ])

    # ═════════════════════════════════════════════════════════════════════
    # TAB 1: 📊 Application Kanban Board
    # ═════════════════════════════════════════════════════════════════════
    with tab_kanban:
        st.subheader("Interactive 6-Stage Application Pipeline")
        st.caption("Manage application lifecycles, advance candidate stages, record interview schedules and recruiter notes.")

        # 6 Swimlane Columns
        swimlanes = st.columns(6)
        stage_header_classes = {
            "Ready to Apply": "hdr-ready",
            "Applied": "hdr-applied",
            "Reply Received": "hdr-reply",
            "Interview Scheduled": "hdr-interview",
            "Rejected": "hdr-rejected",
            "Offer": "hdr-offer",
        }

        for idx, stage_name in enumerate(KANBAN_STAGES):
            with swimlanes[idx]:
                hdr_cls = stage_header_classes.get(stage_name, "hdr-ready")
                cards = kanban_data.get(stage_name, [])
                st.markdown(f'<div class="kanban-col-header {hdr_cls}">{stage_name} ({len(cards)})</div>', unsafe_allow_html=True)

                if not cards:
                    st.caption("No applications in this stage.")

                for card in cards:
                    app_id = card["app_id"]
                    title = html.escape(str(card.get("title") or "Position"))
                    company = html.escape(str(card.get("company") or "Company"))
                    platform = html.escape(str(card.get("platform") or "Direct"))
                    location = html.escape(str(card.get("location") or "Remote"))
                    salary = html.escape(str(card.get("salary_range") or "Not specified"))
                    score = clean_score(card.get("match_score"))
                    score_badge = get_score_badge_html(score)
                    url = str(card.get("url") or "")
                    interview_dt = card.get("interview_date")
                    applied_dt = card.get("applied_date") or card.get("applied_at")

                    date_badge = ""
                    if stage_name == "Interview Scheduled" and interview_dt:
                        date_badge = f'<div style="font-size:0.75rem; color:#fab387; margin-top:4px;">📅 Interview: {str(interview_dt)[:16]}</div>'
                    elif applied_dt:
                        date_badge = f'<div style="font-size:0.75rem; color:#a6adc8; margin-top:4px;">Applied: {str(applied_dt)[:10]}</div>'

                    # Render Card Body
                    st.markdown(f"""
                    <div class="job-card">
                        <div class="job-card-title">{title}</div>
                        <div class="job-card-company">{company}</div>
                        <div>
                            <span class="badge badge-platform">{platform}</span>
                            {score_badge}
                        </div>
                        <div style="margin-top:4px;">
                            <span class="badge badge-location">📍 {location}</span>
                            <span class="badge badge-salary">💰 {salary}</span>
                        </div>
                        {date_badge}
                    </div>
                    """, unsafe_allow_html=True)

                    # Action Row 1: Quick Advance Button
                    next_stage = STAGE_NEXT_MAP.get(stage_name, stage_name)
                    btn_cols = st.columns([1, 1])
                    with btn_cols[0]:
                        if stage_name != "Offer" and stage_name != "Rejected":
                            if st.button(f"➡️ {next_stage}", key=f"adv_{app_id}_{stage_name}", use_container_width=True):
                                with Database() as db_action:
                                    db_action.update_application_stage(app_id, next_stage, f"Quick advanced to {next_stage}")
                                st.session_state.last_action_msg = f"Advanced '{title}' to {next_stage}!"
                                st.rerun()

                    with btn_cols[1]:
                        if stage_name not in ("Rejected", "Offer"):
                            if st.button("🚫 Reject", key=f"rej_{app_id}", use_container_width=True):
                                with Database() as db_action:
                                    db_action.update_application_stage(app_id, "Rejected", "Application marked as rejected")
                                st.session_state.last_action_msg = f"Moved '{title}' to Rejected."
                                st.rerun()

                    # Card Actions Expander: Stage Selector, Recruiter Notes, History Timeline
                    with st.expander("⚙️ Manage & Notes", expanded=False):
                        # Direct Stage Selector
                        new_stage_selection = st.selectbox(
                            "Change Stage",
                            options=KANBAN_STAGES,
                            index=KANBAN_STAGES.index(stage_name),
                            key=f"stage_sel_{app_id}",
                        )
                        if new_stage_selection != stage_name:
                            if st.button("Apply Stage Change", key=f"apply_stage_{app_id}"):
                                with Database() as db_action:
                                    db_action.update_application_stage(
                                        app_id, new_stage_selection, f"Manual stage change to {new_stage_selection}"
                                    )
                                st.session_state.last_action_msg = f"Updated '{title}' stage to {new_stage_selection}."
                                st.rerun()

                        # Recruiter Notes & Interview Form
                        st.markdown("**📝 Recruiter & Interview Notes**")
                        current_notes = card.get("notes") or ""
                        new_notes = st.text_area("Notes", value=current_notes, key=f"notes_{app_id}", height=70)
                        recruiter_info = st.text_input("Recruiter Contact (Name/Email)", key=f"recruiter_{app_id}")
                        interview_input = st.text_input("Interview Date / Time (e.g. 2026-09-05 14:00)", key=f"int_dt_{app_id}")

                        if st.button("💾 Save Notes", key=f"save_note_{app_id}"):
                            with Database() as db_action:
                                db_action.update_application_notes(
                                    app_id=app_id,
                                    notes=new_notes,
                                    interview_date=interview_input.strip() if interview_input.strip() else None,
                                    recruiter_info=recruiter_info.strip() if recruiter_info.strip() else None,
                                )
                            st.session_state.last_action_msg = f"Saved notes for '{title}'."
                            st.rerun()

                        # Chronological Audit History Log
                        st.markdown("**📜 Transition Audit History**")
                        with Database() as db_hist:
                            timeline = db_hist.get_application_timeline(app_id)
                        if timeline:
                            for entry in timeline:
                                t_time = str(entry.get("created_at") or "")[:19]
                                t_stage = entry.get("stage", "")
                                t_note = entry.get("note", "")
                                st.markdown(f"""
                                <div class="timeline-entry">
                                    <div class="timeline-time">⏱️ {t_time} · <strong>{t_stage}</strong></div>
                                    <div class="timeline-note">{t_note}</div>
                                </div>
                                """, unsafe_allow_html=True)
                        else:
                            st.caption("No history events logged.")

                        # Tailored Resume Preview
                        resume_html = card.get("resume_html")
                        if resume_html:
                            st.markdown("**📄 Tailored Resume**")
                            st.download_button(
                                "📥 Download Tailored Resume (HTML)",
                                data=resume_html,
                                file_name=f"resume_{company}_{app_id}.html",
                                mime="text/html",
                                key=f"dl_resume_{app_id}",
                            )

                        # External Job Link
                        if url and url.startswith("http"):
                            st.link_button("🔗 Open Job Listing", url)

                    st.divider()

    # ═════════════════════════════════════════════════════════════════════
    # TAB 2: 📋 Applications Filterable & Sortable Table
    # ═════════════════════════════════════════════════════════════════════
    with tab_table:
        st.subheader("Filterable & Sortable Applications Table")
        st.caption("Search across titles, companies, skills, and notes. Filter by platform, stage, and match score.")

        # Search & Filter Controls
        f_col1, f_col2, f_col3, f_col4 = st.columns([2, 1, 1, 1])
        with f_col1:
            search_query = st.text_input("🔍 Search Applications", placeholder="Search title, company, skills, notes...")
        with f_col2:
            platforms_available = list(set(str(a.get("platform") or "") for a in all_apps if a.get("platform")))
            selected_platforms = st.multiselect("Platform", options=platforms_available, default=platforms_available)
        with f_col3:
            selected_stages = st.multiselect("Stage", options=KANBAN_STAGES, default=KANBAN_STAGES)
        with f_col4:
            min_table_score = st.slider("Min Match Score", 0, 100, 0)

        sort_order = st.selectbox(
            "Sort Applications By",
            options=["Newest First", "Match Score (High to Low)", "Company (A-Z)", "Title (A-Z)", "Stage"],
        )

        # Filter Applications using robust helper function
        filtered_apps = filter_applications(
            all_apps=all_apps,
            search_query=search_query,
            selected_platforms=selected_platforms,
            selected_stages=selected_stages,
            min_table_score=min_table_score,
        )

        # Sort Applications
        if sort_order == "Newest First":
            filtered_apps.sort(key=lambda x: str(x.get("app_updated_at") or x.get("app_created_at") or ""), reverse=True)
        elif sort_order == "Match Score (High to Low)":
            filtered_apps.sort(key=lambda x: clean_score(x.get("match_score")) or 0, reverse=True)
        elif sort_order == "Company (A-Z)":
            filtered_apps.sort(key=lambda x: str(x.get("company") or "").lower())
        elif sort_order == "Title (A-Z)":
            filtered_apps.sort(key=lambda x: str(x.get("title") or "").lower())
        elif sort_order == "Stage":
            filtered_apps.sort(key=lambda x: str(x.get("app_status") or ""))

        st.markdown(f"**Showing {len(filtered_apps)} of {len(all_apps)} applications**")

        if not filtered_apps:
            st.info("No applications match the current filter criteria.")
        else:
            for app in filtered_apps:
                app_id = app["app_id"]
                title = html.escape(str(app.get("title") or "Position"))
                company = html.escape(str(app.get("company") or "Company"))
                platform = html.escape(str(app.get("platform") or "Direct"))
                location = html.escape(str(app.get("location") or "Remote"))
                salary = html.escape(str(app.get("salary_range") or "Not specified"))
                stage = str(app.get("app_status") or "Ready to Apply")
                score = clean_score(app.get("match_score"))
                score_badge = get_score_badge_html(score)
                url = str(app.get("url") or "")
                interview_date = app.get("interview_date")
                applied_date = app.get("applied_date") or app.get("applied_at")

                row_cols = st.columns([3, 2, 2, 2, 3])
                with row_cols[0]:
                    st.markdown(f"**{title}**<br><span style='color:#a6adc8;'>{company} · {platform}</span>", unsafe_allow_html=True)
                with row_cols[1]:
                    st.markdown(f"📍 {location}<br>💰 {salary}", unsafe_allow_html=True)
                with row_cols[2]:
                    st.markdown(f"{score_badge}<br><span style='font-size:0.8rem; color:#fab387;'>Stage: <strong>{stage}</strong></span>", unsafe_allow_html=True)
                with row_cols[3]:
                    if interview_date:
                        st.caption(f"📅 Interview: {str(interview_date)[:16]}")
                    elif applied_date:
                        st.caption(f"Applied: {str(applied_date)[:10]}")
                    else:
                        st.caption("Not applied yet")
                with row_cols[4]:
                    if url and url.startswith("http"):
                        st.link_button("🔗 View Job", url)

                # Row Expander for Quick Stage Modification & Notes
                with st.expander(f"⚙️ Action & Notes: {company} - {title}", expanded=False):
                    act_c1, act_c2 = st.columns(2)
                    with act_c1:
                        new_tbl_stage = st.selectbox(
                            "Update Application Stage",
                            options=KANBAN_STAGES,
                            index=KANBAN_STAGES.index(stage) if stage in KANBAN_STAGES else 0,
                            key=f"tbl_stage_{app_id}",
                        )
                        if new_tbl_stage != stage:
                            if st.button("Apply Stage", key=f"tbl_apply_{app_id}"):
                                with Database() as db_action:
                                    db_action.update_application_stage(
                                        app_id, new_tbl_stage, f"Table update to {new_tbl_stage}"
                                    )
                                st.session_state.last_action_msg = f"Updated '{title}' to {new_tbl_stage}."
                                st.rerun()

                    with act_c2:
                        current_notes = app.get("notes") or ""
                        tbl_notes = st.text_area("Notes / Contact", value=current_notes, key=f"tbl_notes_{app_id}", height=70)
                        if st.button("Save Notes", key=f"tbl_save_notes_{app_id}"):
                            with Database() as db_action:
                                db_action.update_application_notes(app_id=app_id, notes=tbl_notes)
                            st.session_state.last_action_msg = f"Saved notes for '{title}'."
                            st.rerun()

                st.divider()

    # ═════════════════════════════════════════════════════════════════════
    # TAB 3: 🎯 Ready to Apply / Evaluation Candidates
    # ═════════════════════════════════════════════════════════════════════
    with tab_ready:
        st.subheader("Candidates Ready for Application")
        st.caption("High-match roles with tailored resumes ready for review and submission.")

        with Database() as db_ready:
            ready_candidates = db_ready.get_ready_applications()

        if ready_candidates.empty:
            st.info("No applications currently in 'Ready to Apply' stage. Run the pipeline in the **Pipeline & Auth** tab to generate candidates.")
        else:
            st.write(f"**{len(ready_candidates)} Roles Ready for Submission**")
            for _, row in ready_candidates.iterrows():
                app_id = row["app_id"]
                title = html.escape(str(row["title"]))
                company = html.escape(str(row["company"]))
                platform = html.escape(str(row.get("platform") or "Direct"))
                location = html.escape(str(row.get("location") or "Remote"))
                salary = html.escape(str(row.get("salary_range") or "Not specified"))
                score = clean_score(row.get("match_score"))
                score_badge = get_score_badge_html(score)
                reasoning = html.escape(str(row.get("match_reasoning") or ""))
                url = str(row.get("url") or "")
                resume_html = row.get("resume_html") or ""

                st.markdown(f"""
                <div class="job-card">
                    <div class="job-card-title">{title}</div>
                    <div class="job-card-company">{company} · {platform}</div>
                    <div>
                        {score_badge}
                        <span class="badge badge-location">📍 {location}</span>
                        <span class="badge badge-salary">💰 {salary}</span>
                    </div>
                    <p style="font-size:0.85rem; color:#a6adc8; margin-top:8px;"><strong>Evaluation:</strong> {reasoning}</p>
                </div>
                """, unsafe_allow_html=True)

                r_cols = st.columns([1, 1, 2])
                with r_cols[0]:
                    if st.button("✅ Mark as Applied", key=f"mark_applied_{app_id}", use_container_width=True):
                        with Database() as db_action:
                            db_action.update_application_stage(app_id, "Applied", "Applied via job listing link")
                        st.session_state.last_action_msg = f"Marked '{title}' as Applied!"
                        st.rerun()

                with r_cols[1]:
                    if url and url.startswith("http"):
                        st.link_button("🔗 Apply on Portal", url)

                with r_cols[2]:
                    if resume_html:
                        st.download_button(
                            "📥 Download Tailored Resume",
                            data=resume_html,
                            file_name=f"resume_{company}_{app_id}.html",
                            mime="text/html",
                            key=f"ready_dl_resume_{app_id}",
                        )

                with st.expander("📄 Tailored Resume Preview", expanded=False):
                    if resume_html:
                        st.components.v1.html(resume_html, height=400, scrolling=True)
                    else:
                        st.caption("No HTML resume generated.")

                st.divider()

    # ═════════════════════════════════════════════════════════════════════
    # TAB 4: 🔍 Job Board Explorer
    # ═════════════════════════════════════════════════════════════════════
    with tab_explorer:
        st.subheader("All Scraped Listings in DuckDB")
        st.caption("Browse all ingested listings across free direct portals (Himalayas, Remotive, LinkedIn, Naukri, Wellfound, Hirist).")

        with Database() as db_exp:
            all_db_jobs = db_exp.get_all_jobs(sort_desc=True)

        exp_c1, exp_c2, exp_c3 = st.columns([2, 1, 1])
        with exp_c1:
            exp_search = st.text_input("🔍 Search Ingested Jobs", placeholder="Search by title, company, skills...", key="exp_search")
        with exp_c2:
            exp_platforms = list(set(str(j.get("platform") or "") for j in all_db_jobs if j.get("platform")))
            sel_exp_platforms = st.multiselect("Filter Platform", options=exp_platforms, default=exp_platforms, key="sel_exp_platforms")
        with exp_c3:
            sel_eval_status = st.selectbox("Evaluation Status", ["All", "Evaluated Only", "Unevaluated Only"], key="sel_eval_status")

        filtered_jobs = []
        for job in all_db_jobs:
            jp = str(job.get("platform") or "")
            if sel_exp_platforms and jp not in sel_exp_platforms:
                continue

            j_score = clean_score(job.get("match_score"))
            if sel_eval_status == "Evaluated Only" and j_score is None:
                continue
            if sel_eval_status == "Unevaluated Only" and j_score is not None:
                continue

            if exp_search.strip():
                sq = exp_search.strip().lower()
                jt = str(job.get("title") or "").lower()
                jc = str(job.get("company") or "").lower()
                jd = str(job.get("description") or "").lower()
                jsk = str(job.get("skills") or "").lower()
                if sq not in jt and sq not in jc and sq not in jd and sq not in jsk:
                    continue

            filtered_jobs.append(job)

        st.write(f"**Showing {len(filtered_jobs)} of {len(all_db_jobs)} jobs**")

        if not filtered_jobs:
            st.info("No jobs match the current search filters.")
        else:
            for job in filtered_jobs:
                job_id = job["id"]
                j_title = html.escape(str(job.get("title") or "Untitled"))
                j_company = html.escape(str(job.get("company") or "Unknown"))
                j_platform = html.escape(str(job.get("platform") or "Direct"))
                j_location = html.escape(str(job.get("location") or "Remote"))
                j_salary = html.escape(str(job.get("salary_range") or "Not specified"))
                j_score = clean_score(job.get("match_score"))
                j_score_badge = get_score_badge_html(j_score)
                j_url = str(job.get("url") or "")
                j_desc = job.get("description") or ""

                st.markdown(f"""
                <div class="job-card">
                    <div class="job-card-title">{j_title}</div>
                    <div class="job-card-company">{j_company} · {j_platform}</div>
                    <div>
                        {j_score_badge}
                        <span class="badge badge-location">📍 {j_location}</span>
                        <span class="badge badge-salary">💰 {j_salary}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                j_btn_cols = st.columns([1, 1, 3])
                with j_btn_cols[0]:
                    if j_url and j_url.startswith("http"):
                        st.link_button("🔗 View Job", j_url)

                with j_btn_cols[1]:
                    with Database() as db_chk:
                        is_applied = db_chk.is_job_applied(job_id)
                    if not is_applied:
                        if st.button("➕ Create Application", key=f"create_app_{job_id}"):
                            with Database() as db_create:
                                db_create.insert_application(
                                    job_id=job_id,
                                    status="Ready to Apply",
                                    notes="Manually created from Job Explorer",
                                )
                            st.session_state.last_action_msg = f"Created application for '{j_title}'!"
                            st.rerun()
                    else:
                        st.caption("Application exists")

                with st.expander("📖 Full Description & Details", expanded=False):
                    st.write(j_desc if j_desc else "No description available.")

                st.divider()

    # ═════════════════════════════════════════════════════════════════════
    # TAB 5: ⚙️ Pipeline & Auth Management
    # ═════════════════════════════════════════════════════════════════════
    with tab_pipeline:
        st.subheader("Autonomous Pipeline Orchestration")
        st.caption("Trigger multi-portal scraping, ATS evaluation, and tailored resume generation.")

        p_col1, p_col2 = st.columns(2)

        with p_col1:
            st.markdown("### 📋 1. Resume Input")
            uploaded_file = st.file_uploader("Upload custom resume (PDF or JSON)", type=["pdf", "json"])
            if uploaded_file:
                from resume_engine.resume_parser import extract_resume_from_upload
                if st.session_state.resume_data is None:
                    st.session_state.resume_data = extract_resume_from_upload(uploaded_file)
                    if st.session_state.resume_data:
                        st.session_state.resume_text = str(st.session_state.resume_data)
                        st.success(f"✅ Loaded resume: {uploaded_file.name}")

            if st.session_state.resume_data:
                with st.expander("📄 Parsed Resume Preview", expanded=False):
                    st.json(st.session_state.resume_data)
            else:
                st.info("Using default `base_resume.json` if no upload provided.")

            st.markdown("### 🔍 2. Target Search Roles")
            input_keywords = st.text_input(
                "Keywords (comma-separated)",
                value=st.session_state.keywords,
                placeholder="python developer, data engineer, full stack",
            )
            st.session_state.keywords = input_keywords

            pipe_min_score = st.slider("Minimum Match Score for Ready Queue", 0, 100, st.session_state.min_score)
            st.session_state.min_score = pipe_min_score

        with p_col2:
            st.markdown("### 🌐 3. Target Scraper Portals")
            scraper_choices = ["Himalayas", "Remotive", "LinkedIn", "Naukri", "Wellfound", "Hirist"]
            enabled_scrapers = st.multiselect(
                "Active Scrapers",
                options=scraper_choices,
                default=scraper_choices,
            )

            st.markdown("### 🚀 4. Run Autonomous Pipeline")
            st.write("Concurrently scrapes direct portals, eliminates duplicates, evaluates against resume, and generates tailored resumes.")

            if st.button("🚀 Run Full Autonomous Pipeline", type="primary", use_container_width=True):
                kw_list = [k.strip() for k in input_keywords.split(",") if k.strip()]
                if not kw_list:
                    st.warning("Please enter at least one keyword.")
                else:
                    prog_placeholder = st.empty()
                    status_placeholder = st.empty()

                    def ui_progress_callback(msg: str) -> None:
                        prog_placeholder.caption(f"⚡ {msg}")

                    with st.spinner("Executing end-to-end pipeline..."):
                        res = run_pipeline(
                            resume_text=st.session_state.resume_text,
                            resume_json=st.session_state.resume_data,
                            keywords=kw_list,
                            min_score=pipe_min_score,
                            enabled_sources=enabled_scrapers,
                            progress_callback=ui_progress_callback,
                        )

                    prog_placeholder.empty()
                    status_placeholder.success(
                        f"✅ Scraped: {res['total_scraped']} | Newly Stored: {res['newly_stored']} | "
                        f"Evaluated: {res['evaluated']} | Ready to Apply: {res['ready']}"
                    )
                    st.rerun()

        st.markdown("---")
        st.subheader("🧹 Database Maintenance & Stale Purging")
        db_m_col1, db_m_col2 = st.columns(2)
        with db_m_col1:
            if st.button("🗑️ Purge Deprecated Platform Records", use_container_width=True):
                with Database() as db_purge:
                    purged = db_purge.purge_deprecated_platforms()
                st.success(f"Purged {purged} stale records from deprecated platforms.")
                st.rerun()

        with db_m_col2:
            with Database() as db_stats:
                stats_jobs = len(db_stats.get_all_jobs())
                stats_apps = len(db_stats.get_all_applications_table())
            st.caption(f"DuckDB Database: `{stats_jobs}` jobs, `{stats_apps}` applications stored.")

    # ─── Footer ──────────────────────────────────────────────────────────
    st.markdown("---")
    st.caption("Built with ❤️ using Streamlit · Scrapers: Himalayas, Remotive, LinkedIn, Naukri, Wellfound, Hirist")


if __name__ == "__main__":
    main()
