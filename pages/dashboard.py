import streamlit as st

from database.db import (
    get_all_candidates,
    get_candidate_count_by_status
)

st.title("Dashboard")

total = len(get_all_candidates())

completed = get_candidate_count_by_status("Completed")
partial = get_candidate_count_by_status("Partial")
failed = get_candidate_count_by_status("Failed")
needs_review = get_candidate_count_by_status("Needs Review")

col1, col2, col3, col4, col5 = st.columns(5)

col1.metric("Total Candidates", total)
col2.metric("Completed", completed)
col3.metric("Partial", partial)
col4.metric("Needs Review", needs_review)
col5.metric("Failed", failed)