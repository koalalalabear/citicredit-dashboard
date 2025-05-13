import re
import pandas as pd
import fitz  # PyMuPDF
import streamlit as st
from io import BytesIO
from datetime import datetime
from utils.mapping import load_mapping, save_mapping


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
        (?P<info>.*?)(?=\s+\d{1,3}(?:,\d{3})*\.\d{2})             # Info (non-greedy) until a number
        \s+(?P<amount1>\d{1,3}(?:,\d{3})*\.\d{2})?                # First amount (withdrawal OR deposit)
        (?:\s+(?P<amount2>\d{1,3}(?:,\d{3})*\.\d{2}))?            # Second amount (optional)
        \s+(?P<balance>\d{1,3}(?:,\d{3})*\.\d{2})                 # Balance
    """, re.VERBOSE | re.MULTILINE)
        


    transactions = []
    for match in pattern.finditer(text):
        data = match.groupdict()
        amount1 = data.pop('amount1')
        amount2 = data.pop('amount2')

        # Logic to decide withdrawal vs deposit
        if amount2:  # If there are two amounts
            data['withdrawal'] = float(amount1.replace(',', '')) if amount1 else None
            data['deposit'] = float(amount2.replace(',', '')) if amount2 else None
        else:
            # Only one amount => assume it's a deposit if balance increases, else withdrawal
            data['withdrawal'] = None
            data['deposit'] = float(amount1.replace(',', '')) if amount1 else None

        if data['balance']:
            data['balance'] = float(data['balance'].replace(',', ''))
        else:
            data['balance'] = None

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
    
    # Load existing merchant-category mappings
    merchant_to_category = load_mapping()

    # Assign categories based on the cleaned description (merchant name)
    df["Category"] = df["clean_description"].map(merchant_to_category).fillna("")

    # Return the DataFrame with the new Category column
    return df


# --- Extract Balance B/F (if exists) ---
def get_balance_bf(df):
    """Extract balance value for 'BALANCE B/F' and return it."""
    balance_row = df[df["clean_description"].str.upper() == "BALANCE B F"]
    if not balance_row.empty:
        return balance_row.iloc[0]["balance"]
    return None

# --- Extract Balance C/F (if exists) ---
def get_balance_cf(df):
    """Extract balance value for the last transaction row (C/F)."""
    if not df.empty:
        return df.iloc[-1]["balance"]
    return None


            
# --- Sidebar Upload ---
uploaded_file = st.sidebar.file_uploader("Upload your UOB bank statement PDF", type=["pdf"])

if uploaded_file:

    year = st.sidebar.number_input("Select year", min_value=2000, max_value=2100, value=datetime.now().year)

    st.sidebar.success(f"✅ Loaded: {uploaded_file.name}")
    st.sidebar.markdown(f"**Selected Year:** `{year}`")

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

            # --- Get and display Balance B/F & C/F---
            
            col1, col2 = st.columns(2)

            with col1:
                balance_bf = get_balance_bf(df)
                if balance_bf is not None:
                    st.metric("💰 Balance B/F", f" {balance_bf:,.2f}")

            with col2:
                balance_cf = get_balance_cf(df)
                if balance_cf is not None:
                    st.metric("📈 Balance C/F", f" {balance_cf:,.2f}")
                                        

            # --- Remove Balance B/F row before displaying the table ---
            df_cleaned = df[df["clean_description"].str.upper() != "BALANCE B F"]

            # ✅ Display the cleaned DataFrame
            st.subheader("📊 Transaction Table")
            st.dataframe(df_cleaned)
else:
    st.info("📤 Upload a UOB bank statement PDF using the sidebar to get started.")