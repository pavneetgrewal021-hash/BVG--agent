import streamlit as st
import pandas as pd
from database.db import get_connection
from datetime import datetime

def create_batch(batch_name, total):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO batches (batch_name, uploaded_at, total_candidates)
        VALUES (?, ?, ?)
    """, (batch_name, datetime.now(), total))
    batch_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return batch_id


st.title("📤 Upload Candidates")

uploaded_file = st.file_uploader("Upload Candidate Excel", type=["xlsx"])

if uploaded_file:

    df = pd.read_excel(uploaded_file)

    required_columns = ["CandidateId", "Name", "Email", "Phone"]

    if not all(col in df.columns for col in required_columns):
        st.error(f"❌ Excel must have these columns: {required_columns}")
        st.stop()


    errors = []
    if df["CandidateId"].isnull().any():
        errors.append("Some rows have missing CandidateId")
    if df["Email"].isnull().any():
        errors.append("Some rows have missing Email")
    if df.duplicated(subset=["CandidateId"]).any():
        errors.append("Duplicate CandidateIds found in the file")

    if errors:
        for e in errors:
            st.error(f"❌ {e}")
        st.stop()

    st.success(f"✅ {len(df)} candidates loaded successfully")
    st.dataframe(df, use_container_width=True)

    batch_name = st.text_input(
        "Batch name",
        value=f"Batch_{datetime.now().strftime('%Y%m%d_%H%M')}"
    )

    if st.button("💾 Save Candidates"):

        batch_id = create_batch(batch_name, len(df))

        progress = st.progress(0)
        status_text = st.empty()

        CHUNK_SIZE = 1000
        total = len(df)
        saved = 0

        conn = get_connection()
        cursor = conn.cursor()

        for start in range(0, total, CHUNK_SIZE):
            chunk = df.iloc[start:start + CHUNK_SIZE]

            candidates_data = [
                (str(row["CandidateId"]), row["Name"], row["Email"], str(row["Phone"]))
                for _, row in chunk.iterrows()
            ]

            cursor.executemany("""
                INSERT INTO candidates (candidate_id, name, email, phone)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    name  = excluded.name,
                    email = excluded.email,
                    phone = excluded.phone
            """, candidates_data)

            batch_links = [(batch_id, str(row["CandidateId"])) for _, row in chunk.iterrows()]
            cursor.executemany("""
                INSERT INTO batch_candidates (batch_id, candidate_id)
                VALUES (?, ?)
            """, batch_links)

            conn.commit()
            saved += len(chunk)

            progress.progress(saved / total)
            status_text.text(f"Saving... {saved}/{total} candidates")

        conn.close()

        progress.progress(1.0)
        status_text.text("✅ Done!")
        st.success(f"✅ {total} candidates saved under **{batch_name}**")
        st.info(f"Batch ID: {batch_id} — visible in History page")