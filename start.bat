@echo off
title Job Finder - Remote Job Search Dashboard
echo ========================================
echo   Job Finder - Remote Job Search Dashboard
echo ========================================
echo.
echo Starting Streamlit server...
echo The dashboard will open at http://localhost:8501
echo.
echo Press Ctrl+C to stop the server.
echo ========================================
echo.
cd /d "%~dp0"
python -m streamlit run dashboard/app.py --server.headless true --server.port 8501
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start. Make sure Python and Streamlit are installed.
    echo Run: pip install -r requirements.txt
    pause
)
