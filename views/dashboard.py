import streamlit as st
import common


st.title("Audit Overview")

try:
    kpis = common.get_kpis()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total clients", f"{kpis['total_clients']:,}")
    c2.metric("Total $ paid", f"${float(kpis['total_paid'] or 0):,.2f}")
    c3.metric("Number of projects", f"{kpis['total_projects']:,}")
except Exception as e:
    st.warning(f"Couldn't load the summary cards: {e}")

st.divider()
st.page_link("views/explorer.py", label="Open the Data Explorer", icon="🔍")
