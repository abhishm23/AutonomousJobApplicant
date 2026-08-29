import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    DB_PATH = os.getenv("DB_PATH", "data/jobs.duckdb")
    TARGET_ROLES = os.getenv("TARGET_ROLES", "Data Scientist, Automation Engineer, AI Augmented Engineer")
    MIN_SALARY_USD = int(os.getenv("MIN_SALARY_USD", 100000))
    PREFERRED_REMOTE_LEVEL = os.getenv("PREFERRED_REMOTE_LEVEL", "Fully Remote")
    WKHTMLTOPDF_PATH = os.getenv("WKHTMLTOPDF_PATH", r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe")

config = Config()
