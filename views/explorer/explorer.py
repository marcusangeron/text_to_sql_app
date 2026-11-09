
import streamlit as st
from google.cloud import bigquery

import common

_, bq_client = common.get_clients()

with st.sidebar:
    st.info(
        "💡 **Sample prompts to try:**\n\n"
        "- *How many clients have a completed assessment?*\n"
        "- *Total transaction amounts grouped by organization name*\n"
        "- *Count enrollments by project type description*"
    )

st.title("Audit Data Explorer")

# ---------------------------------------------------------
# Chat history (session state persists when switching pages)
# ---------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="assistant" if msg["role"] == "assistant" else None):
        st.markdown(msg["content"])
        if "sql" in msg:
            st.code(msg["sql"], language="sql")
        if "dataframe" in msg:
            st.dataframe(msg["dataframe"], use_container_width=True)

user_query = st.chat_input("Ask a question about your audit data...")

if user_query:
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    with st.chat_message("assistant"):
        with st.spinner("Generating SQL query and querying BigQuery..."):
            try:
                sql_query = common.generate_sql(user_query)
                st.markdown("### Generated SQL")
                st.code(sql_query, language="sql")

                if not common.is_safe_select(sql_query):
                    blocked = "Blocked: only a single read-only SELECT query is allowed."
                    st.error(blocked)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": blocked,
                        "sql": sql_query,
                    })
                    st.stop()

                job_config = bigquery.QueryJobConfig(maximum_bytes_billed=common.MAX_BYTES_BILLED)
                df = bq_client.query(sql_query, job_config=job_config).to_dataframe()

                if not df.empty:
                    st.dataframe(df, use_container_width=True)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": f"Found {len(df)} records.",
                        "sql": sql_query,
                        "dataframe": df,
                    })
                else:
                    st.success("Query executed successfully but returned 0 rows.")
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": "Query executed successfully but returned 0 rows.",
                        "sql": sql_query,
                    })

            except Exception as e:
                st.error(f"Execution Error: {e}")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Error: {e}",
                })
