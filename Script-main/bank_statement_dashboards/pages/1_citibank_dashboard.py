import re
import pandas as pd
import fitz  # PyMuPDF
import streamlit as st
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Citibank Statement Parser", layout="wide")
st.title("📄 Citibank PDF Statement Parser")

# --- Function to extract text from PDF ---
def extract_text_from_pdf(file_bytes):
    """Extract all text from the PDF using PyMuPDF."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception as e:
        st.error(f"❌ Failed to read PDF: {e}")
        return ""

# --- Function to extract year from filename ---
def get_year_from_filename(name):
    """Extract year from the filename."""
    match = re.search(r'(\d{4})', name)
    return int(match.group(1)) if match else datetime.now().year

# --- Function to parse transactions with auto-categorization ---
def parse_transactions(text, year):
    """Extract transactions from PDF text and categorize using regex."""
    pattern = r"""
        (?P<date>\d{2}\s[A-Z]{3})        # 17 JAN
        \s+
        (?P<merchant>.+?)                # FAIRPRICE FINEST
        \s+
        (?:[A-Z]+\s+){1,3}               # Skip location (SINGAPORE SG)
        (?P<amount>\d+\.\d{2})           # 12.10
    """

    merchant_patterns = {
        "Groceries": re.compile(r"little farms|fairprice|ntuc|7-eleven|cheers", re.IGNORECASE),
        "Carbs": re.compile(r"epidor|bakery|toast|onalu|brotherbird", re.IGNORECASE),
        "Sugar": re.compile(r"starbucks|fruce|candy|sweets", re.IGNORECASE),
        "Beauty & Wellness": re.compile(r"yoga|guardian|watsons", re.IGNORECASE),
    }

    transactions = []
    for m in re.finditer(pattern, text, re.VERBOSE):
        try:
            merchant_name = m.group("merchant").strip().lower()
            category = ""
            for cat, regex in merchant_patterns.items():
                if regex.search(merchant_name):
                    category = cat
                    break

            transactions.append({
                "Date": f"{m.group('date')} {year}",
                "Merchant": m.group("merchant").strip(),
                "Amount": float(m.group("amount")),
                "Month": m.group('date').split()[1],
                "Category": category,
            })
        except Exception:
            continue
    return transactions

# --- Sidebar Upload ---
uploaded_file = st.sidebar.file_uploader("Upload your Citibank PDF", type=["pdf"])

if uploaded_file:
    file_name = uploaded_file.name
    year = get_year_from_filename(file_name)

    st.sidebar.success(f"✅ Loaded: {file_name}")
    st.sidebar.markdown(f"**Detected Year:** `{year}`")

    # Extract text from PDF
    text = extract_text_from_pdf(uploaded_file.read())

    if not text.strip():
        st.error("❌ No text extracted — this may be a scanned PDF.")
    else:
        transactions = parse_transactions(text, year)

        if not transactions:
            st.warning("⚠️ No transactions found. Check PDF format.")
        else:
            df = pd.DataFrame(transactions)
            df["Date"] = pd.to_datetime(df["Date"], format="%d %b %Y")

            st.success(f"✅ Found {len(df)} transactions")

            # --- Dynamic Category Input ---
            custom_categories = st.text_input(
                "✏️ Enter custom category options (comma-separated)",
                value="Groceries, Carbs, Sugar, Beauty & Wellness, Food, Transport"
            )
            category_options = [c.strip() for c in custom_categories.split(",") if c.strip()]

            # --- Manual Categorization ---
            if "" in df["Category"].values:
                st.subheader("📝 Categorize Unlabeled Transactions")
                uncategorized_df = df[df["Category"] == ""].copy()

                for i, row in uncategorized_df.iterrows():
                    col1, col2, col3 = st.columns([2, 2, 3])
                    with col1:
                        st.markdown(f"**{row['Date'].strftime('%d %b %Y')}**")
                    with col2:
                        st.markdown(f"_{row['Merchant']}_")
                    with col3:
                        selected = st.selectbox(
                            "Select Category",
                            options=[""] + category_options,
                            key=f"cat_{i}"
                        )
                        if selected:
                            df.at[i, "Category"] = selected

            # --- Data Table ---
            st.dataframe(df.sort_values("Date"), use_container_width=True)

            # --- Summary ---
            total = df["Amount"].sum()
            st.metric("Total Spent 💸", f"${total:.2f}")

            # --- Chart: Monthly Spend ---
            st.subheader("📊 Monthly Spend")
            chart = df.groupby("Month")["Amount"].sum()
            st.bar_chart(chart)

            # --- Interactive Category Breakdown by Month ---
            st.subheader("📆 View Category Breakdown by Month")

            # Dynamically get available months from parsed transactions
            available_months = sorted(df["Month"].unique().tolist())

            # User selects a month
            selected_month = st.selectbox("Select a month", available_months)

            # Filter data based on selected month
            filtered_df = df[df["Month"] == selected_month]

            if filtered_df.empty:
                st.warning("⚠️ No transactions found for this month.")
            else:
                # Group by category and sum
                category_summary = filtered_df.groupby("Category")["Amount"].sum().sort_values(ascending=False)

                st.subheader(f"📊 Spend by Category — {selected_month}")

                col1, col2 = st.columns(2)

                with col1:
                    st.bar_chart(category_summary)

                with col2:
                    st.dataframe(category_summary.reset_index().rename(columns={"Amount": "Total Spend"}))



            # --- Download Button ---
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Download CSV",
                data=csv,
                file_name=file_name.replace(".pdf", "_transactions_with_categories.csv"),
                mime="text/csv"
            )
else:
    st.info("📤 Upload a Citibank PDF using the sidebar to get started.")
