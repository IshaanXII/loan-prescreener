"""
Loan Eligibility / Credit-Risk Pre-Screener App
Decision-support / Analytics - Use Case #5

Features:
- Input form for applicant data
- Rule-based risk score (transparent, explainable) 0-100
- Explanation of score drivers
- Approve / Refer / Reject output
- Optional Gemini AI explanation (free API key)
- Batch scoring with sample_data.csv
"""
import streamlit as st
import pandas as pd
import math
import requests

st.set_page_config(page_title="Loan Pre-Screener", page_icon="🏦", layout="wide")

# ---------- Scoring Logic (pure python, testable) ----------
def calc_emi(principal, annual_rate_pct=11.0, months=60):
    if months <= 0:
        return 0
    r = annual_rate_pct / 12 / 100
    if r == 0:
        return principal / months
    emi = principal * r * ((1 + r) ** months) / (((1 + r) ** months) - 1)
    return round(emi, 2)

def score_applicant(d):
    """
    d dict keys: age, monthly_income, employment_type, years_in_job,
    cibil_score, existing_emi, loan_amount, tenure_months, past_defaults
    Returns: eligibility_score (0-100), risk_score (0-100), decision, drivers list, metrics dict
    """
    age = d["age"]
    income = max(d["monthly_income"], 1)
    emp = d["employment_type"]
    years = d["years_in_job"]
    cibil = d["cibil_score"]
    existing_emi = d["existing_emi"]
    loan_amt = d["loan_amount"]
    tenure = d["tenure_months"]
    defaults = d["past_defaults"]

    new_emi = calc_emi(loan_amt, 11.0, tenure)
    total_emi = existing_emi + new_emi
    dti_after = total_emi / income
    annual_income = income * 12
    lti = loan_amt / max(annual_income, 1)

    # Component scores 0-100
    # 1. Credit history (30%)
    cibil_norm = max(0, min(100, (cibil - 300) / 600 * 100))
    if defaults >= 3:
        cibil_norm *= 0.5
    elif defaults == 2:
        cibil_norm *= 0.7
    elif defaults == 1:
        cibil_norm *= 0.85

    # 2. Affordability / DTI (25%) - total DTI after loan
    # <=30% = 100, 50% = 50, >=60% = 0
    if dti_after <= 0.30:
        dti_score = 100
    elif dti_after >= 0.60:
        dti_score = 0
    else:
        dti_score = 100 - ((dti_after - 0.30) / 0.30 * 100)

    # 3. Loan-to-income (20%) - LTI <=2 = 100, >=6 = 0
    if lti <= 2:
        lti_score = 100
    elif lti >= 6:
        lti_score = 0
    else:
        lti_score = 100 - ((lti - 2) / 4 * 100)

    # 4. Employment stability (15%)
    emp_base = {"Salaried": 85, "Self-Employed": 70, "Business": 65, "Unemployed": 20}
    base = emp_base.get(emp, 60)
    stability_bonus = min(years * 3, 15)
    emp_score = max(0, min(100, base + stability_bonus - (10 if emp == "Unemployed" else 0)))

    # 5. Age / profile (10%)
    if 25 <= age <= 55:
        age_score = 90
    elif 21 <= age < 25 or 55 < age <= 60:
        age_score = 70
    else:
        age_score = 40

    eligibility = round(
        cibil_norm * 0.30 + dti_score * 0.25 + lti_score * 0.20 + emp_score * 0.15 + age_score * 0.10, 1
    )
    risk = round(100 - eligibility, 1)

    if eligibility >= 70 and cibil >= 650 and dti_after <= 0.5 and emp != "Unemployed":
        decision = "APPROVE"
    elif eligibility >= 50:
        decision = "REFER"
    else:
        decision = "REJECT"
    # Hard reject rules
    if defaults >= 3:
        decision = "REJECT"
    if cibil < 600 and defaults >= 2:
        decision = "REJECT"
    if dti_after > 0.65:
        decision = "REJECT"
    if emp == "Unemployed" and loan_amt > income * 12:
        decision = "REJECT"

    drivers = []
    # Positive / negative drivers
    if cibil >= 750:
        drivers.append(("✅", f"Excellent CIBIL {cibil} (+{round(cibil_norm*0.30,1)} pts)"))
    elif cibil >= 650:
        drivers.append(("➖", f"Fair CIBIL {cibil} - improve for better rate"))
    else:
        drivers.append(("❌", f"Low CIBIL {cibil} - major risk driver"))

    if dti_after <= 0.30:
        drivers.append(("✅", f"Affordable: Total DTI {dti_after:.1%} (EMI ₹{total_emi:,.0f})"))
    elif dti_after <= 0.50:
        drivers.append(("➖", f"Stretched: Total DTI {dti_after:.1%} - borderline affordability"))
    else:
        drivers.append(("❌", f"Unaffordable: Total DTI {dti_after:.1%} exceeds 50% limit"))

    if lti <= 2:
        drivers.append(("✅", f"Healthy loan-to-income {lti:.1f}x annual income"))
    elif lti <= 4:
        drivers.append(("➖", f"High loan-to-income {lti:.1f}x - consider lower amount/longer tenure"))
    else:
        drivers.append(("❌", f"Excessive loan-to-income {lti:.1f}x annual income"))

    if defaults > 0:
        drivers.append(("❌", f"{defaults} past default(s)/delays - hurts trust"))
    else:
        drivers.append(("✅", "Clean repayment history"))

    if emp == "Unemployed":
        drivers.append(("❌", "Unemployed - no stable income source"))
    elif years < 2:
        drivers.append(("➖", f"Low job stability ({years} yr) in {emp}"))
    else:
        drivers.append(("✅", f"Stable: {years} yrs as {emp}"))

    metrics = {
        "new_emi": new_emi,
        "total_emi": total_emi,
        "dti_after": dti_after,
        "lti": lti,
        "cibil_norm": round(cibil_norm, 1),
        "dti_score": round(dti_score, 1),
        "lti_score": round(lti_score, 1),
        "emp_score": round(emp_score, 1),
        "age_score": age_score,
    }
    return eligibility, risk, decision, drivers, metrics


def gemini_explain(api_key, applicant, eligibility, decision, drivers, metrics):
    """Call Gemini 1.5 Flash free API. Returns text or error string."""
    if not api_key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key.strip()}"
    driver_text = "; ".join([f"{e} {t}" for e, t in drivers])
    prompt = f"""You are a loan officer assistant. Explain in simple language (under 150 words) the loan pre-screen result.

Applicant: Age {applicant['age']}, Income Rs.{applicant['monthly_income']}/month, {applicant['employment_type']} ({applicant['years_in_job']} yrs), CIBIL {applicant['cibil_score']}, Existing EMI Rs.{applicant['existing_emi']}, Requested Loan Rs.{applicant['loan_amount']} for {applicant['tenure_months']} months, Purpose {applicant.get('loan_purpose','-')}, Past defaults {applicant['past_defaults']}.
Result: Eligibility Score {eligibility}/100, Decision {decision}, New EMI Rs.{metrics['new_emi']}, Total DTI {metrics['dti_after']:.1%}.
Key drivers: {driver_text}.
Give 2-3 actionable tips to improve approval chance. Be friendly, no disallowed content, add disclaimer this is a pre-screen not final approval."""
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        r = requests.post(url, json=payload, timeout=25)
        if r.status_code != 200:
            return f"⚠️ Gemini API error {r.status_code}: {r.text[:300]}"
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"⚠️ Gemini call failed: {e}"


# ---------- UI ----------
st.title("🏦 Loan Eligibility / Credit-Risk Pre-Screener")
st.caption("Decision-support App • Rule-based transparent score + Gemini AI explanation • Approve / Refer / Reject")

with st.sidebar:
    st.header("⚙️ Settings")
    api_key = st.text_input("Gemini Free API Key (optional)", type="password",
        help="Get free key from Google AI Studio (aistudio.google.com). App works without it using rule-based explanation.")
    st.markdown("[Get free Gemini API key](https://aistudio.google.com/app/apikey)")
    st.divider()
    st.markdown("**Decision thresholds**\n\n✅ ≥70 Approve\n\n🟡 50-69 Refer\n\n🔴 <50 Reject")

tab1, tab2 = st.tabs(["📝 Single Applicant", "📊 Batch Scoring (sample data)"])

with tab1:
    with st.form("loan_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            name = st.text_input("Applicant Name", "Test Applicant")
            age = st.slider("Age", 18, 75, 30)
            monthly_income = st.number_input("Monthly Income (₹)", 10000, 1000000, 60000, step=5000)
        with c2:
            employment_type = st.selectbox("Employment Type", ["Salaried", "Self-Employed", "Business", "Unemployed"])
            years_in_job = st.slider("Years in current job/business", 0, 30, 3)
            cibil_score = st.slider("CIBIL / Credit Score", 300, 900, 720)
        with c3:
            existing_emi = st.number_input("Existing Monthly EMI/Debt (₹)", 0, 500000, 8000, step=1000)
            loan_amount = st.number_input("Requested Loan Amount (₹)", 50000, 10000000, 500000, step=50000)
            tenure_months = st.selectbox("Tenure (months)", [12, 24, 36, 48, 60, 84, 96, 120, 180, 240], index=4)
        c4, c5 = st.columns(2)
        with c4:
            loan_purpose = st.selectbox("Loan Purpose", ["Home", "Personal", "Business", "Auto", "Education"])
        with c5:
            past_defaults = st.selectbox("Past defaults / 90+ day delays", [0, 1, 2, 3], index=0)
        submitted = st.form_submit_button("🔍 Check Eligibility", use_container_width=True)

    if submitted:
        applicant = {
            "age": age, "monthly_income": monthly_income, "employment_type": employment_type,
            "years_in_job": years_in_job, "cibil_score": cibil_score, "existing_emi": existing_emi,
            "loan_amount": loan_amount, "tenure_months": tenure_months,
            "loan_purpose": loan_purpose, "past_defaults": past_defaults, "name": name,
        }
        elig, risk, decision, drivers, m = score_applicant(applicant)

        # Result banner
        color = {"APPROVE": "green", "REFER": "orange", "REJECT": "red"}[decision]
        emoji = {"APPROVE": "✅", "REFER": "🟡", "REJECT": "🔴"}[decision]
        st.markdown(f":{color}[## {emoji} Decision: {decision} — Eligibility {elig}/100 | Risk {risk}/100]")
        st.progress(int(elig) / 100)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Eligibility Score", f"{elig}/100")
        k2.metric("Risk Score", f"{risk}/100")
        k3.metric("New EMI @11%", f"₹{m['new_emi']:,.0f}")
        k4.metric("Total DTI", f"{m['dti_after']:.1%}")

        st.subheader("📌 Why this score? (Score Drivers)")
        for e, t in drivers:
            st.write(f"{e} {t}")

        with st.expander("🔬 Score breakdown (transparent weights)"):
            st.write(f"- Credit history (30%): {m['cibil_norm']}/100")
            st.write(f"- Affordability DTI (25%): {m['dti_score']}/100")
            st.write(f"- Loan-to-income (20%): {m['lti_score']}/100")
            st.write(f"- Employment stability (15%): {m['emp_score']}/100")
            st.write(f"- Age profile (10%): {m['age_score']}/100")
            st.write(f"- LTI = {m['lti']:.2f}x | Total EMI = ₹{m['total_emi']:,.0f}")

        st.subheader("🤖 AI Officer Note")
        if api_key:
            with st.spinner("Asking Gemini..."):
                ai_text = gemini_explain(api_key, applicant, elig, decision, drivers, m)
            st.write(ai_text)
        else:
            # Rule-based fallback
            if decision == "APPROVE":
                st.info(f"{name} looks eligible. CIBIL and DTI are healthy. Bank will likely approve subject to document verification. Tip: keep credit utilisation <30% to get best rate.")
            elif decision == "REFER":
                st.warning(f"{name} is borderline. Improve CIBIL above 750, reduce existing EMI, or ask for lower amount/longer tenure, then re-apply. Manual review by officer recommended.")
            else:
                st.error(f"{name} is currently high-risk. Main blockers above marked ❌. Action: repay dues, wait 6 months, rebuild CIBIL, then re-apply with co-applicant or collateral.")
            st.caption("Add Gemini API key in sidebar for personalised AI explanation.")

        st.caption("⚠️ Disclaimer: This is an educational pre-screen, not a bank approval. Rate assumed 11% for EMI estimate.")

with tab2:
    st.subheader("Batch pre-screen — sample_data.csv")
    st.write("Upload a CSV or use the bundled sample of 10 applicants to demo.")
    try:
        sample_df = pd.read_csv("sample_data.csv")
        st.dataframe(sample_df, use_container_width=True)
        if st.button("▶️ Score sample data"):
            rows = []
            for _, r in sample_df.iterrows():
                d = {
                    "age": int(r["age"]), "monthly_income": float(r["monthly_income"]),
                    "employment_type": r["employment_type"], "years_in_job": int(r["years_in_job"]),
                    "cibil_score": int(r["cibil_score"]), "existing_emi": float(r["existing_emi"]),
                    "loan_amount": float(r["loan_amount"]), "tenure_months": int(r["tenure_months"]),
                    "past_defaults": int(r["past_defaults"]),
                }
                elig, risk, dec, _, m = score_applicant(d)
                rows.append({**r.to_dict(), "eligibility": elig, "risk": risk,
                             "decision": dec, "new_emi": m["new_emi"]})
            out = pd.DataFrame(rows)
            st.success("Scored!")
            st.dataframe(out[["name", "monthly_income", "cibil_score", "loan_amount",
                              "eligibility", "risk", "decision", "new_emi"]], use_container_width=True)
            st.bar_chart(out.set_index("name")["eligibility"])
            csv = out.to_csv(index=False).encode()
            st.download_button("⬇️ Download results CSV", csv, "loan_results.csv", "text/csv")
    except FileNotFoundError:
        st.error("sample_data.csv not found next to app.py")
    up = st.file_uploader("Or upload your own CSV (same columns)", type="csv")
    if up is not None:
        df = pd.read_csv(up)
        st.dataframe(df.head(), use_container_width=True)
        st.info("Use same scoring by clicking Score after placing file as sample_data.csv format. Columns needed: age, monthly_income, employment_type, years_in_job, cibil_score, existing_emi, loan_amount, tenure_months, past_defaults")
