import re
import pandas as pd
import fitz  # PyMuPDF
import streamlit as st
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Banking account dashboard", layout="wide")
st.title("📄 UOB bank account dashboard")

# --- Function to extract text from PDF ---
def extract_text_from_pdf(file_bytes):
    """Extract all text from the PDF using PyMuPDF."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception as e:
        st.error(f"❌ Failed to read PDF: {e}")
        return ""

# --- Data cleaning---
def extract_alphabets(desc, info):
    # Combine text and remove 'SINGAPORE SG' (case-insensitive, allowing whitespace/newlines)
    combined = f"{desc} {info}".replace('\n', ' ').strip() if desc or info else ''
    
    # Remove variations of "SINGAPORE SG" (e.g., "SINGAPORE   SG", "singapore sg", etc.)
    cleaned = re.sub(r'\bSINGAPORE\s+SG\b', '', combined, flags=re.IGNORECASE)

    # Extract only alphabetic characters
    alpha_only = re.sub(r'[^A-Za-z]+', ' ', cleaned).strip()

    return alpha_only

def extract_withdrawal(desc, info):
    # Combine text and remove 'SINGAPORE SG' (case-insensitive, allowing whitespace/newlines)
    cleaned = f"{desc} {info}".replace('\n', ' ').strip() if desc or info else ''
    
    # Normalize commas for easier float conversion
    cleaned = cleaned.replace(',', '')
    
    # Find all numbers with exactly 2 decimal places
    matches = re.findall(r'\d+\.\d{2}', cleaned)
    
    # Return the first match as float, or None if not found
    return float(matches[0]) if matches else None

def impute_clean_withdrawal(df):

    for i in range(1, len(df)):
        current_balance = df.loc[i, "balance"]
        prev_balance = df.loc[i - 1, "balance"]
        deposit_value = df.loc[i, "deposit"]

        if pd.notna(deposit_value) and current_balance < prev_balance:
            df.loc[i, "clean_withdrawal"] = deposit_value
            df.loc[i, "deposit"] = None

    return df


# --- Function to parse transactions ---
def parse_month_end(text, year):
    """Extract transactions from statement text including date, description, info, withdrawal, deposit, and balance."""
    pattern = re.compile(r"""
        (?P<date>\d{2}\s\w{3})\s+                                 # e.g. 01 Mar
        (?P<description>[A-Z0-9 -]+(?:\s[A-Z0-9 -]+)*)\s+         # Bolded description
        (?P<info>.*?)(?=\s+\d{1,3}(?:,\d{3})*\.\d{2}|\s{2,})      # Info (non-greedy) until a number
        (?:(?P<withdrawal>\d{1,3}(?:,\d{3})*\.\d{2})|(?:-))?\s*   # Withdrawal (optional)
        (?:(?P<deposit>\d{1,3}(?:,\d{3})*\.\d{2})|(?:-))?\s*      # Deposit (optional)
        (?P<balance>\d{1,3}(?:,\d{3})*\.\d{2})                    # Balance
    """, re.VERBOSE | re.MULTILINE)
    


    transactions = []
    for match in pattern.finditer(text):
        data = match.groupdict()
        for field in ['withdrawal', 'deposit', 'balance']:
            if data[field]:
                data[field] = float(data[field].replace(',', ''))
            else:
                data[field] = None
        data['date'] = f"{data['date']} {year}"
        transactions.append(data)

    
    # Create DataFrame and clean it
    df = pd.DataFrame(transactions)
    df["date"] = pd.to_datetime(df["date"], format="%d %b %Y", errors="coerce")
    df = df[df["date"].notna()].copy()  # Keep only rows with valid dates

    # Create new columns - clean_description and clean_withdrawal
    df["clean_description"] = df.apply(lambda row: extract_alphabets(row["description"], row["info"]), axis=1)
    df["clean_withdrawal"] = df.apply(lambda row: extract_withdrawal(row["description"], row["info"]), axis=1)

    # If 'clean_withdrawal' is None, fill it with the value from 'withdrawal'
    df["clean_withdrawal"] = df["clean_withdrawal"].fillna(df["withdrawal"])

    # Apply the imputation logic
    df = impute_clean_withdrawal(df)

    # Drop unnecessary columns to avoid duplicates
    df = df.drop(columns=["description", "info", "withdrawal"], errors='ignore')

    # Rearrange columns (no need to insert if they already exist)
    cols = list(df.columns)

    # Ensure that 'clean_description' and 'clean_withdrawal' are at the right positions
    if "clean_description" not in cols:
        cols.insert(2, "clean_description")

    if "clean_withdrawal" not in cols:
        cols.insert(3, "clean_withdrawal")

    # Reorder the DataFrame columns
    df = df[["date", "clean_description", "clean_withdrawal", "deposit", "balance"]]


    return df

# --- Sidebar Upload ---
uploaded_file = st.sidebar.file_uploader("Upload your UOB bank statement PDF", type=["pdf"])

if uploaded_file:
    # Prompt user to manually select year
    year = st.sidebar.number_input("Select year", min_value=2000, max_value=2100, value=datetime.now().year)

    st.sidebar.success(f"✅ Loaded: {uploaded_file.name}")
    st.sidebar.markdown(f"**Selected Year:** `{year}`")

    # Extract text from PDF
    text = extract_text_from_pdf(uploaded_file.read())

    if not text.strip():
        st.error("❌ No text extracted — this may be a scanned PDF.")
    else:
        df = parse_month_end(text, year)

        if df.empty:
            st.warning("⚠️ No transactions found. Check PDF format.")
        else:
            df["date"] = pd.to_datetime(df["date"], format="%d %b %Y", errors="coerce")
            st.success(f"✅ Found {len(df)} transactions")

            # ✅ Display the DataFrame
            st.subheader("📊 Transaction Table")
            st.dataframe(df)
