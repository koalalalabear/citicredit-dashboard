
import re
from datetime import datetime

import fitz        # PyMuPDF
import pandas as pd
import streamlit as st


st.set_page_config(page_title="UOB Account Dashboard", layout="wide")
st.title("📄 UOB Bank Account Dashboard")


# --- 1) PDF → raw text ---
def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract all text from the PDF using PyMuPDF."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except Exception as e:
        st.error(f"❌ Failed to read PDF: {e}")
        return ""


# --- 2) Clean description text ---
def extract_alphabets(desc: str, info: str) -> str:
    combined = f"{desc} {info}".replace("\n", " ").strip()
    # remove "SINGAPORE SG" variants
    cleaned = re.sub(r"\bSINGAPORE\s+SG\b", "", combined, flags=re.IGNORECASE)
    # keep only letters and spaces
    return re.sub(r"[^A-Za-z]+", " ", cleaned).strip()


# --- 3) Parse transactions robustly ---
def parse_month_end(text: str, year: int) -> pd.DataFrame:    # allow info to span lines (DOTALL), and make description truly non‑greedy
    pattern = re.compile(r"""
        (?P<date>\d{2}\s\w{3})\s+                       # e.g. 26 Sep

        # description + info can now include anything up until the first number
        (?P<description>.+?)                            # non‑greedy, multi‑line
        (?P<info>.*?)(?=\s+\d{1,3}(?:,\d{3})*\.\d{2})    # then info up to a number

        \s+(?P<amount1>\d{1,3}(?:,\d{3})*\.\d{2})?       # first amount (opt)
        (?:\s+(?P<amount2>\d{1,3}(?:,\d{3})*\.\d{2}))?   # second amount (opt)
        \s+(?P<balance>\d{1,3}(?:,\d{3})*\.\d{2})        # balance
    """, re.VERBOSE | re.MULTILINE | re.DOTALL)
    
    transactions = []
    prev_bal = None

    for m in pattern.finditer(text):
        d = m.groupdict()
        d["description"] = re.sub(r'(?<=[A-Za-z])\s+(?=[A-Za-z])', '', d["description"])
        d["description"] = re.sub(r'\s+', ' ', d["description"]).strip()


        a1, a2 = d.pop("amount1"), d.pop("amount2")
        # parse numbers
        cur_bal = float(d["balance"].replace(",", "")) if d["balance"] else 0.0
        f1 = float(a1.replace(",", "")) if a1 else None
        f2 = float(a2.replace(",", "")) if a2 else None

        # classify withdrawal / deposit
        if f1 is not None and f2 is not None:
            # two amounts present
            d["withdrawal"], d["deposit"] = f1, f2

        elif f1 is not None:
            # single amount: use keywords
            desc_low = d["description"].lower()
            credit_keys = ["deposit", "inward credit", "inward cr", "misc cr", "interest credit"]
            if any(k in desc_low for k in credit_keys):
                d["deposit"], d["withdrawal"] = f1, 0.0
            else:
                # fallback to balance diff if we have prev
                if prev_bal is not None:
                    if cur_bal > prev_bal:
                        d["deposit"], d["withdrawal"] = f1, 0.0
                    else:
                        d["withdrawal"], d["deposit"] = f1, 0.0
                else:
                    # no prev -> assume withdrawal
                    d["withdrawal"], d["deposit"] = f1, 0.0

        else:
            # no amounts found
            d["withdrawal"], d["deposit"] = 0.0, 0.0

        # finalize
        d["balance"] = cur_bal
        d["date"] = f"{d['date']} {year}"
        transactions.append(d)
        prev_bal = cur_bal

    # fallback pattern if nothing found
    if not transactions:
        st.warning("No transactions found with primary pattern—trying fallback…")
        alt = re.compile(r"""
            (?P<date>\d{2}\s\w{3})\s+
            (?P<description>[A-Za-z0-9 \-]+?)\s+
            (?P<amount>\d{1,3}(?:,\d{3})*\.\d{2})\s+
            (?P<balance>\d{1,3}(?:,\d{3})*\.\d{2})
        """, re.VERBOSE)
        for g in alt.finditer(text):
            gd = g.groupdict()
            amt = float(gd["amount"].replace(",", ""))
            bal = float(gd["balance"].replace(",", ""))
            transactions.append({
                "date"       : f"{gd['date']} {year}",
                "description": gd["description"].strip(),
                "info"       : "",
                "withdrawal" : amt,
                "deposit"    : 0.0,
                "balance"    : bal
            })

    df = pd.DataFrame(transactions)

    # ensure cols exist
    for col in ["date", "description", "info", "withdrawal", "deposit", "balance"]:
        if col not in df.columns:
            df[col] = "" if col in ["date","description","info"] else 0.0

    # parse date and drop invalid
    df["date"] = pd.to_datetime(df["date"], format="%d %b %Y", errors="coerce")
    df = df[df["date"].notna()].copy()

    # clean description
    df["clean_description"] = df.apply(
        lambda r: extract_alphabets(r["description"], r["info"]), axis=1
    )

    # second‑pass: if both withdrawal & deposit non‑zero, fix via balance diff
    for i in range(1, len(df)):
        prev, cur = df.iloc[i-1], df.iloc[i]
        if cur["withdrawal"] and cur["deposit"]:
            diff = cur["balance"] - prev["balance"]
            if diff > 0 and abs(diff - cur["deposit"]) < 0.01:
                df.at[i, "withdrawal"] = 0.0
            elif diff < 0 and abs(-diff - cur["withdrawal"]) < 0.01:
                df.at[i, "deposit"] = 0.0

    return df[["date", "clean_description", "withdrawal", "deposit", "balance"]]


# --- 4) Balance B/F & C/F helpers ---
def get_balance_bf(df: pd.DataFrame):
    bf = df[df["clean_description"].str.upper().str.contains("BALANCE B F")]
    return float(bf.iloc[0]["balance"]) if not bf.empty else None


def get_balance_cf(df: pd.DataFrame):
    return float(df.iloc[-1]["balance"]) if not df.empty else None


# --- 5) Streamlit UI ---
uploaded_file = st.sidebar.file_uploader(
    "Upload your UOB statement PDF", type=["pdf"]
)

if uploaded_file:
    year = st.sidebar.number_input(
        "Select year", min_value=2000, max_value=2100,
        value=datetime.now().year
    )
    st.sidebar.success(f"Loaded: {uploaded_file.name}")
    st.sidebar.markdown(f"Year: `{year}`")

    pdf_bytes = uploaded_file.read()
    text = extract_text_from_pdf(pdf_bytes)

    if not text.strip():
        st.error("No text extracted – is it a scanned PDF?")
    else:
        df = parse_month_end(text, year)
        if df.empty:
            st.warning("No transactions found. Check PDF format.")
        else:
            st.success(f"Found {len(df)} transactions")

            # show Balance B/F & C/F
            c1, c2 = st.columns(2)
            with c1:
                bf = get_balance_bf(df)
                if bf is not None:
                    st.metric("💰 Balance B/F", f"{bf:,.2f}")
            with c2:
                cf = get_balance_cf(df)
                if cf is not None:
                    st.metric("📈 Balance C/F", f"{cf:,.2f}")

            # remove the B/F row
            df_clean = df[~df["clean_description"]
                           .str.upper()
                           .str.contains("BALANCE B F")]

            # show totals
            tot_w = df_clean["withdrawal"].sum()
            tot_d = df_clean["deposit"].sum()
            x1, x2 = st.columns(2)
            with x1:
                st.metric("💸 Total Withdrawals", f"${tot_w:,.2f}")
            with x2:
                st.metric("💵 Total Deposits", f"${tot_d:,.2f}")

            # show table & download
            st.subheader("📊 Transactions")
            st.dataframe(df_clean)

            csv = df_clean.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download CSV", csv,
                "uob_transactions.csv", "text/csv"
            )
