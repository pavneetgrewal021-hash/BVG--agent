import streamlit as st

st.set_page_config(
    page_title="BGV Agent",
    page_icon="📄",
    layout="wide"
)

st.title("Background Verification Agent")

st.write("Welcome to the BGV System")

st.info("""
Modules:
- Dashboard
- Candidate Upload
- Processing
- History
- Settings
""")