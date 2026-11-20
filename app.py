"""
Compatibility entry — tools and hosts that expect app.py land here.
Dashboard code: streamlit_app.py

Run locally:
  streamlit run streamlit_app.py
  streamlit run app.py          # same UI
"""

# Streamlit runs this file; importing runs the real dashboard once.
import streamlit_app  # noqa: F401