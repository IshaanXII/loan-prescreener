# Loan Eligibility / Credit-Risk Pre-Screener

Decision-support App — Use Case #5

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Get shareable link (free)
**Option A — Streamlit Cloud (recommended):**
1. Push this folder to GitHub
2. Go to share.streamlit.io → New app → select repo + `app.py`
3. Deploy. Add Gemini key in sidebar at runtime (not in code).

**Option B — HuggingFace Spaces:**
1. New Space → Streamlit → upload `app.py`, `requirements.txt`, `sample_data.csv`
2. Same — enter Gemini key in sidebar.

## Gemini Free API Key
1. Go to https://aistudio.google.com/app/apikey → Create key (free)
2. Paste in sidebar → AI Officer Note becomes personalised.
3. Without key, app still works with rule-based explanation.

## Files
- `app.py` — full app (form + score + batch)
- `sample_data.csv` — 10 applicants demo
- `requirements.txt`
- `Project_Document.docx` — end-term report
- `Video_Script.md` — 2-min demo script
