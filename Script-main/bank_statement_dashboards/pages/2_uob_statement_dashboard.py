import re
from datetime import datetime
import fitz        # PyMuPDF
import pandas as pd
import streamlit as st

st.set_page_config(page_title="UOB Account Dashboard", layout="wide")
st.title("📄 UOB Bank Account Dashboard")

# --- 1) PDF → raw text with formatting ---
def extract_text_from_pdf(file_bytes: bytes) -> tuple[str, list]:
    """Extract text and formatting information from PDF using PyMuPDF."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        
        # Extract text with formatting information
        formatted_blocks = []
        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            formatted_blocks.append({
                                "text": span["text"],
                                "bold": bool(span["flags"] & 2**4),  # Bold flag
                                "bbox": span["bbox"],
                                "size": span["size"]
                            })
        
        doc.close()
        return text, formatted_blocks
    except Exception as e:
        st.error(f"❌ Failed to read PDF: {e}")
        return "", []

# --- 2) Clean description text ---
def extract_alphabets(desc: str, info: str) -> str:
    # Combine and clean line breaks
    combined = f"{desc} {info}".replace("\n", " ").strip()

    # Remove patterns like "29 AUG", "02 Sep" (date format dd MMM)
    combined = re.sub(r'\b\d{2}\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b', '', combined, flags=re.IGNORECASE)

    # Remove "SINGAPORE SG" variants
    combined = re.sub(r"\bSINGAPORE\s+SG\b", "", combined, flags=re.IGNORECASE)

    # Remove extra spaces from removing phrases
    combined = re.sub(r'\s{2,}', ' ', combined)

    # Keep only alphanumerics and spaces
    return re.sub(r"[^A-Za-z0-9\s]+", " ", combined).strip()


# --- 3) Parse credit card transactions ---
def parse_credit_card_transactions(text: str, formatted_blocks: list, year: int) -> pd.DataFrame:
    """
    Parse UOB credit card transactions using font formatting and newline patterns
    """
    transactions = []
    
    # Method 1: Use bold text to identify transaction types
    if formatted_blocks:
        transactions = parse_with_formatting(formatted_blocks, year)
 
    # Method 2: Fallback to newline pattern analysis
    if not transactions:
        st.info("No bold formatting found, using newline pattern analysis...")
        transactions = parse_with_newline_patterns(text, year)
    
    # Method 3: Final fallback to line-by-line parsing
    if not transactions:
        st.info("Newline patterns failed, trying line-by-line parsing...")
        transactions = parse_line_by_line_v2(text, year)
    
    # Create DataFrame
    df = pd.DataFrame(transactions)
    
    if df.empty:
        return df
    
    # Ensure required columns exist
    required_cols = ["date","description", "info", "withdrawal", "deposit", "balance"]
    for col in required_cols:
        if col not in df.columns:
            if col in ["date", "description", "info", "transaction_type"]:
                df[col] = ""
            else:
                df[col] = 0.0
    
    # Parse dates
    if not df.empty and 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df[df['date'].notna()].copy()  # filter out invalid dates (NaT)
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')  # convert to 'YYYY-MM-DD' string format

    
    # Clean descriptions
    if not df.empty:
        df["clean_description"] = df.apply(
            lambda r: extract_alphabets(
                str(r.get("description", "")), 
                str(r.get("info", ""))
            ), 
            axis=1
)

    # Final data cleaning step: Remove rows where both withdrawal and deposit are 0 or null
    if not df.empty:
        df = df[~((df['deposit'].fillna(0) == 0) & (df['withdrawal'].fillna(0) == 0))]

    return df[["date", "transaction_type", "clean_description", "withdrawal", "deposit", "balance"]]


def parse_with_formatting(formatted_blocks: list, year: int) -> list:
    """Parse transactions using bold text as transaction type indicators"""
    transactions = []
    current_transaction = None
    
    for i, block in enumerate(formatted_blocks):
        text = block["text"].strip()
        if not text:
            continue
        
        # Bold text likely indicates transaction type/header
        if block["bold"] and len(text) > 3:
            # Save previous transaction
            if current_transaction:
                transactions.append(finalize_transaction(current_transaction, year))
            
            # Start new transaction
            current_transaction = {
                "transaction_type": text,
                "description_parts": [],
                "amounts": [],
                "location": ""
            }
        
        # Non-bold text is likely description or amounts
        elif current_transaction:
            # Check if this text contains amounts
            amount_matches = re.findall(r'\d{1,3}(?:,\d{3})*\.\d{2}', text)
            if amount_matches:
                current_transaction["amounts"].extend(amount_matches)
            
            # Check for location indicators
            if "SINGAPORE" in text.upper() or text.upper().endswith(" SG"):
                current_transaction["location"] = text
            else:
                # Add to description
                current_transaction["description_parts"].append(text)
    
    # Don't forget the last transaction
    if current_transaction:
        transactions.append(finalize_transaction(current_transaction, year))
    
    return transactions

def parse_with_newline_patterns(text: str, year: int) -> list:
    """Parse transactions using newline patterns and text structure"""
    transactions = []
    lines = text.split('\n')
    current_transaction = None
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # Pattern 1: All caps line (likely transaction type)
        if line.isupper() and len(line) > 5 and not re.match(r'^[\d\s,.]+$', line):
            # Save previous transaction
            if current_transaction:
                transactions.append(finalize_transaction(current_transaction, year))
            
            # Start new transaction
            current_transaction = {
                "transaction_type": line,
                "description_parts": [],
                "amounts": [],
                "location": ""
            }
        
        # Pattern 2: Line starts with common transaction prefixes
        elif re.match(r'^(NETS|Misc|PAYNOW|Inward|Balance|DR-|CR-)', line, re.IGNORECASE):
            # Save previous transaction
            if current_transaction:
                transactions.append(finalize_transaction(current_transaction, year))
            
            # Start new transaction
            current_transaction = {
                "transaction_type": line,
                "description_parts": [],
                "amounts": [],
                "location": ""
            }
        
        # Pattern 3: Standalone amount line (likely end of transaction)
        elif re.match(r'^\d{1,3}(?:,\d{3})*\.\d{2}$', line) and current_transaction:
            current_transaction["amounts"].append(line)
        
        # Pattern 4: Line with location info
        elif "SINGAPORE" in line.upper() or line.upper().endswith(" SG"):
            if current_transaction:
                current_transaction["location"] = line
        
        # Pattern 5: Regular description line
        elif current_transaction:
            # Check if line contains amounts within it
            amount_matches = re.findall(r'\d{1,3}(?:,\d{3})*\.\d{2}', line)
            if amount_matches:
                current_transaction["amounts"].extend(amount_matches)
                # Remove amounts from description
                desc_line = re.sub(r'\d{1,3}(?:,\d{3})*\.\d{2}', '', line).strip()
                if desc_line:
                    current_transaction["description_parts"].append(desc_line)
            else:
                current_transaction["description_parts"].append(line)
    
    # Don't forget the last transaction
    if current_transaction:
        transactions.append(finalize_transaction(current_transaction, year))
    
    return transactions

def finalize_transaction(transaction_data: dict, year: int) -> dict:
    """Convert raw transaction data into standardized format"""
    trans_type = transaction_data.get("transaction_type", "")
    description = " ".join(transaction_data.get("description_parts", [])).strip()
    amounts = transaction_data.get("amounts", [])
    location = transaction_data.get("location", "")
    
    # Parse amounts
    parsed_amounts = [float(amt.replace(',', '')) for amt in amounts if amt]
    main_amount = parsed_amounts[0] if parsed_amounts else 0.0
    
    # Extract date from description if present
    date_match = re.search(r'(\d{1,2}\s+\w{3})', description)
    trans_date = date_match.group(1) if date_match else "01 Jan"
    
    # Determine if it's credit or debit
    is_credit = any(keyword in trans_type.lower() for keyword in [
        'inward', 'credit', 'cr-', 'deposit', 'refund', 'reversal'
    ])
    
    return {
        'date': f"{trans_date} {year}",
        'transaction_type': trans_type,
        'description': description,
        'info': location,
        'withdrawal': 0.0 if is_credit else main_amount,
        'deposit': main_amount if is_credit else 0.0,
        'balance': parsed_amounts[-1] if len(parsed_amounts) > 1 else main_amount
    }

def parse_line_by_line_v2(text: str, year: int) -> list:
    """
    Fallback parser that processes text line by line
    """
    lines = text.split('\n')
    transactions = []
    current_transaction = {}
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
            
        # Check if line contains an amount
        amount_match = re.search(r'(\d{1,3}(?:,\d{3})*\.\d{2})', line)
        
        # Check if line starts a new transaction type
        transaction_types = ['NETS', 'Misc DR', 'PAYNOW', 'Inward CR', 'Balance']
        is_transaction_start = any(line.startswith(t) for t in transaction_types)
        
        if is_transaction_start:
            # Save previous transaction if exists
            if current_transaction:
                transactions.append(current_transaction.copy())
                current_transaction = {}
            
            current_transaction['transaction_type'] = line
            current_transaction['description'] = ''
            
        elif amount_match and current_transaction:
            # This line contains the amount
            amount = float(amount_match.group(1).replace(',', ''))
            
            # Determine if it's a credit or debit
            if 'inward cr' in current_transaction.get('transaction_type', '').lower():
                current_transaction['deposit'] = amount
                current_transaction['withdrawal'] = 0.0
            else:
                current_transaction['withdrawal'] = amount
                current_transaction['deposit'] = 0.0
                
            current_transaction['balance'] = amount  # Temporary
            
        elif current_transaction:
            # Add to description
            if current_transaction['description']:
                current_transaction['description'] += ' ' + line
            else:
                current_transaction['description'] = line
    
    # Don't forget the last transaction
    if current_transaction:
        transactions.append(current_transaction)
    
    # Create list of dictionaries for consistency
    transaction_list = []
    for trans in transactions:
        # Add missing columns
        if "date" not in trans:
            trans["date"] = "01 Jan " + str(year)
        if "info" not in trans:
            trans["info"] = ""
            
        transaction_list.append(trans)
    
    return transaction_list

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
    text, formatted_blocks = extract_text_from_pdf(pdf_bytes)

    if not text.strip():
        st.error("No text extracted – is it a scanned PDF?")
    else:
        # Show raw text and formatting info for debugging
        with st.expander("🔍 View Raw PDF Text (for debugging)"):
            st.text(text[:2000] + "..." if len(text) > 2000 else text)
            
        with st.expander("🎨 View Formatting Info (for debugging)"):
            if formatted_blocks:
                bold_blocks = [block for block in formatted_blocks[:20] if block["bold"]]
                st.json(bold_blocks)
            else:
                st.info("No formatting information extracted")
        
        df = parse_credit_card_transactions(text, formatted_blocks, year)
        
        if df.empty:
            st.warning("No transactions found. Check PDF format.")
        else:
            st.success(f"Found {len(df)} transactions")

            # Show Balance B/F & C/F
            c1, c2 = st.columns(2)
            with c1:
                bf = get_balance_bf(df)
                if bf is not None:
                    st.metric("💰 Balance B/F", f"{bf:,.2f}")
            with c2:
                cf = get_balance_cf(df)
                if cf is not None:
                    st.metric("📈 Balance C/F", f"{cf:,.2f}")

            # Remove the B/F row
            df_clean = df[~df["clean_description"]
                           .str.upper()
                           .str.contains("BALANCE B F")]

            # Show totals
            tot_w = df_clean["withdrawal"].sum()
            tot_d = df_clean["deposit"].sum()
            x1, x2 = st.columns(2)
            with x1:
                st.metric("💸 Total Withdrawals", f"${tot_w:,.2f}")
            with x2:
                st.metric("💵 Total Deposits", f"${tot_d:,.2f}")        

            # Hard codeded logic to fix the row where Transaction Type is "One Bonus Interest"
            mask = df_clean['transaction_type'] == 'One Bonus Interest'
            df_clean.loc[mask, 'deposit'] = df.loc[mask, 'withdrawal']
            df_clean.loc[mask, 'withdrawal'] = 0
            # Reset index
            st.dataframe(df_clean.reset_index(drop=True))

                        
            
            # Show table & download
            st.subheader("📊 Transactions")
            st.dataframe(df_clean[["date", "transaction_type", "clean_description", "withdrawal", "deposit", "balance"]])


            csv = df_clean[["date", "transaction_type", "clean_description", "withdrawal", "deposit", "balance"]].to_csv(index=False).encode("utf-8")

            st.download_button(
                "Download CSV", csv,
                "uob_transactions.csv", "text/csv"
            )
else:
    st.info("📤 Upload a UOB PDF bank statement using the sidebar to get started.")