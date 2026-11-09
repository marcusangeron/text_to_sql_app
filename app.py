import streamlit as st
import common

st.set_page_config(
    page_title="hi-audit | Text-to-SQL Assistant",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

common.apply_styles()
common.get_clients()      # fail fast with a clear error if GCP auth is misconfigured
common.render_sidebar()   # logo + messaging appear on every page

# ---------------------------------------------------------
# Navigation
# ---------------------------------------------------------
pages = [
    st.Page("views/dashboard.py", title="Dashboard", icon="📊", default=True),
    st.Page("views/explorer.py", title="Data Explorer", icon="🔍"),
]

# position="top" keeps the sidebar free for the logo and branding.
# On older Streamlit versions (< 1.46), delete the position argument.
nav = st.navigation(pages, position="top")
nav.run()
