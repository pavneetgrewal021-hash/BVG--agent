import streamlit as st
import pandas as pd

from database.db import get_all_candidates

st.title("Candidate List")

candidates = get_all_candidates()

if candidates:

    df = pd.DataFrame(
        candidates,
        columns=[
            "Candidate ID",
            "Name",
            "Email",
            "Phone",
            "Status"
        ]
    )

    st.dataframe(df)

else:
    st.warning("No candidates found")