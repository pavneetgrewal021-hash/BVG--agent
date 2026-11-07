import streamlit as st
import pandas as pd
from database.db import get_connection

def get_all_batches():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, batch_name, uploaded_at, total_candidates, completed, partial, failed
        FROM batches
        ORDER BY uploaded_at DESC
    """)
    data = cursor.fetchall()
    conn.close()
    return data

def get_batch_candidates(batch_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.candidate_id, c.name, c.email, c.phone, c.status
        FROM candidates c
        JOIN batch_candidates bc ON c.candidate_id = bc.candidate_id
        WHERE bc.batch_id = ?
    """, (batch_id,))
    data = cursor.fetchall()
    conn.close()
    return data

def get_candidate_documents(candidate_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT document_type, file_name
        FROM documents
        WHERE candidate_id = ?
    """, (candidate_id,))
    data = cursor.fetchall()
    conn.close()
    return data


st.title("📜 Batch History")

batches = get_all_batches()

if not batches:
    st.info("No batches uploaded yet. Go to Upload Candidates to get started.")
    st.stop()


df_batches = pd.DataFrame(
    batches,
    columns=["ID", "Batch Name", "Uploaded At", "Total", "Completed", "Partial", "Failed"]
)

st.dataframe(df_batches, use_container_width=True)

st.divider()

st.subheader("🔍 Drill into a Batch")

batch_options = {f"Batch {b[0]} — {b[1]} ({b[2]})": b[0] for b in batches}
selected_label = st.selectbox("Select batch", list(batch_options.keys()))
selected_batch_id = batch_options[selected_label]

candidates = get_batch_candidates(selected_batch_id)

if not candidates:
    st.warning("No candidates found in this batch.")
    st.stop()

df_candidates = pd.DataFrame(
    candidates,
    columns=["Candidate ID", "Name", "Email", "Phone", "Status"]
)


def color_status(val):
    colors = {
        "Completed": "background-color: #d4edda; color: #155724",
        "Partial":   "background-color: #fff3cd; color: #856404",
        "Failed":    "background-color: #f8d7da; color: #721c24",
        "Pending":   "background-color: #e2e3e5; color: #383d41",
        "Needs Review": "background-color: #ffe5d0; color: #8a3b00"
    }
    return colors.get(val, "")

st.dataframe(
    df_candidates.style.map(color_status, subset=["Status"]),
    use_container_width=True
)

st.divider()


st.subheader("📄 Candidate Document Details")

candidate_options = {f"{c[0]} — {c[1]}": c[0] for c in candidates}
selected_candidate = st.selectbox("Select candidate", list(candidate_options.keys()))
selected_candidate_id = candidate_options[selected_candidate]

docs = get_candidate_documents(selected_candidate_id)

if not docs:
    st.warning("No documents found for this candidate.")
else:
    df_docs = pd.DataFrame(
        docs,
        columns=["Document Type", "File Name"]
    )
    st.dataframe(df_docs, use_container_width=True)