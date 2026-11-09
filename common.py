import os
import re
import streamlit as st
from google import genai
from google.genai import types
from google.cloud import bigquery

# ---------------------------------------------------------
# Environment & Configuration
# ---------------------------------------------------------
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", os.environ.get("GCP_PROJECT", "hi-audit"))
AI_LOCATION = os.environ.get("AI_LOCATION", "global")   # gemini-3.8-flash worked with "global"
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-3.8-flash")
DATASET_IDS = [
    d.strip()
    for d in os.environ.get("BQ_DATASETS", "hmis_data_import,HMIS_reference").split(",")
    if d.strip()
]
MAX_BYTES_BILLED = int(os.environ.get("MAX_BYTES_BILLED", 5 * 10**9))  # 5 GB cap per query
KPI_DATASET = "hmis_data_import"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_SOURCE = os.path.join(BASE_DIR, "assets", "logo.png")

# ---------------------------------------------------------
# Styling
# ---------------------------------------------------------
def apply_styles():
    st.markdown("""
<style>
[data-testid="stSidebar"] {
    min-width: 380px;
    max-width: 380px;
}
.brand-title {
    text-align: center;
    font-size: 30px;
    font-weight: 700;
    margin-top: 10px;
    margin-bottom: 0px;
}
.brand-subtitle {
    text-align: center;
    color: #a0a0a0;
    margin-bottom: 20px;
}

/* KPI Metric Cards: Border, Background, and Spacing */
div[data-testid="stMetric"] {
    background-color: rgba(128, 128, 128, 0.08);
    border: 1px solid rgba(128, 128, 128, 0.25);
    border-radius: 10px;
    padding: 16px 20px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
}
</style>
""", unsafe_allow_html=True)


def render_sidebar():
    """Logo, branding, and project info. Shown on every page."""
    with st.sidebar:
        if os.path.exists(LOGO_SOURCE):
            st.image(LOGO_SOURCE, use_container_width=True)

        st.markdown(
            """
            <div class="brand-title">🔍 hi-audit</div>
            <div class="brand-subtitle">
                AI-Powered Audit & Analytics
                <div class="brand-credit" style="text-align: center; color: #888; font-size: 13px; font-style: italic; margin-top: 5px;">Developed by Data Action Partners</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.divider()
        st.write(f"**GCP Project:** `{PROJECT_ID}`")
        st.write(f"**BQ Datasets:** `{', '.join(DATASET_IDS)}`")
        st.write(f"**Model:** `{MODEL_NAME}`")
        st.divider()

        st.warning(
            "This dataset contains client-level records. Don't share query results "
            "outside people who are authorized to see them."
        )

# ---------------------------------------------------------
# Clients
# ---------------------------------------------------------
@st.cache_resource
def init_clients():
    ai_client = genai.Client(vertexai=True, project=PROJECT_ID, location=AI_LOCATION)
    bq_client = bigquery.Client(project=PROJECT_ID)
    return ai_client, bq_client


def get_clients():
    """Return (ai_client, bq_client), or show an error and stop the page."""
    try:
        return init_clients()
    except Exception as e:
        st.error(f"Failed to initialize Google Cloud clients: {e}")
        st.stop()

# ---------------------------------------------------------
# KPIs (live numbers from BigQuery, cached for an hour)
# ---------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_kpis() -> dict:
    _, bq_client = init_clients()
    sql = f"""
    SELECT
      (SELECT COUNT(DISTINCT PersonalID)
         FROM `{PROJECT_ID}.{KPI_DATASET}.client`) AS total_clients,
      (SELECT SUM(SAFE_CAST(Amount AS NUMERIC))
         FROM `{PROJECT_ID}.{KPI_DATASET}.fsr_2023_2026`) AS total_paid,
      (SELECT COUNT(DISTINCT ProjectID)
         FROM `{PROJECT_ID}.{KPI_DATASET}.project`) AS total_projects
    """
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED)
    row = list(bq_client.query(sql, job_config=job_config).result())[0]
    return {
        "total_clients": row["total_clients"],
        "total_paid": row["total_paid"],
        "total_projects": row["total_projects"],
    }

# ---------------------------------------------------------
# Dataset schema (cached for an hour; failures are not cached)
# ---------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def get_dataset_schema() -> str:
    _, bq_client = init_clients()
    schema_info = []
    for dataset_id in DATASET_IDS:
        for table in bq_client.list_tables(dataset_id):
            t = bq_client.get_table(table)
            cols = [f"{field.name} ({field.field_type})" for field in t.schema]
            schema_info.append(
                f"Table `{t.project}.{t.dataset_id}.{t.table_id}` columns: {', '.join(cols)}"
            )
    return "\n".join(schema_info)

# ---------------------------------------------------------
# SQL helpers: cleanup and read-only safety check
# ---------------------------------------------------------
FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|EXPORT|CALL|EXECUTE)\b",
    re.IGNORECASE,
)


def clean_sql(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def is_safe_select(sql: str) -> bool:
    body = sql.strip().rstrip(";").strip()
    if not body or ";" in body:
        return False
    if not re.match(r"^(SELECT|WITH)\b", body, re.IGNORECASE):
        return False
    return not FORBIDDEN.search(body)

# ---------------------------------------------------------
# Text-to-SQL generator
# ---------------------------------------------------------
def generate_sql(user_prompt: str) -> str:
    ai_client, _ = init_clients()
    try:
        schema_context = get_dataset_schema()
    except Exception as e:
        raise RuntimeError(
            f"Could not read the schema for datasets {DATASET_IDS}. "
            f"Check that they exist and the service account can view them. Details: {e}"
        )

    if not schema_context.strip():
        raise RuntimeError(f"Datasets {DATASET_IDS} have no tables, or none are visible to this app.")

    system_prompt = f"""You are an expert BigQuery SQL developer.
Project: {PROJECT_ID}
Datasets: {", ".join(DATASET_IDS)}

Schema:
{schema_context}

Notes about HMIS data:
- `client` holds client details and is keyed by PersonalID.
- `enrollment` links clients to projects (PersonalID, ProjectID, EnrollmentID, EntryDate, MoveInDate).
- `project` holds project metadata; `organization` holds organization details (join on OrganizationID).
- `assessment`, `services`, and `exit` link to enrollments through EnrollmentID.
- `fsr_2023_2026` holds financial records (Client_ID, ProjectID, Transaction_Date, Amount, Service).
- To describe project type, join `HMIS_reference.ProjectType` on `refproj.Value = p.ProjectType`.

CRITICAL FILTERING RULES:
1. DO NOT assume or add WHERE clause filters unless the user explicitly requested them in the prompt.
2. DO NOT filter by status, active flags, date ranges (e.g., current year, past 30 days), non-null checks, or positive amounts unless explicitly stated by the user.
3. If the user asks for "total clients", count ALL rows/PersonalIDs without adding filters.
4. If the user asks for "transactions by organization", aggregate across all dates and statuses without restricting timeframes.
5. Only use WHERE clauses for:
   - Specific entity filters requested by the user (e.g., "for organization XYZ", "in 2024").
   - Foreign key join conditions (use standard INNER/LEFT JOIN ... ON clauses for joins, not WHERE).

FEW-SHOT EXAMPLES:

User: "How many total clients are there?"
SQL:
SELECT COUNT(DISTINCT PersonalID) AS total_clients
FROM `{PROJECT_ID}.hmis_data_import.client`

User: "Total transaction amount by organization name"
SQL:
SELECT o.OrganizationName, SUM(SAFE_CAST(f.Amount AS NUMERIC)) AS total_amount
FROM `{PROJECT_ID}.hmis_data_import.fsr_2023_2026` AS f
JOIN `{PROJECT_ID}.hmis_data_import.project` AS p ON f.ProjectID = p.ProjectID
JOIN `{PROJECT_ID}.hmis_data_import.organization` AS o ON p.OrganizationID = o.OrganizationID
GROUP BY o.OrganizationName

OUTPUT FORMAT:
- Return ONLY executable Standard BigQuery SQL.
- No Markdown fences, no backticks, no comments, no explanations.
"""

    response = ai_client.models.generate_content(
        model=MODEL_NAME,
        contents=f"User Request: {user_prompt}",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.0,
        ),
    )
    return clean_sql(response.text)

