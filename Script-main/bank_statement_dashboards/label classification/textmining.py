"""
Classification
-------------
A script that uses ML for classification and organizes data nicely in a DataFrame

Optional:
- Usage: python textmining.py 
- Dependencies: 
    pip install pandas scikit-learn
- Pre-Req: 
    labeled data : labeled_transactions.csv
"""

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report

# Step 1: Prepare labeled data
# Columns: clean_description, category
df_labeled = pd.read_csv("labeled_transactions.csv")

# Step 2: Train-test split
X = df_labeled["clean_description"]
y = df_labeled["category"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42
)

# Step 3: TF-IDF + Classifier pipeline
pipeline = Pipeline([
    ('tfidf', TfidfVectorizer(
        stop_words="english",
        max_features=1000,    # You can tune this
        ngram_range=(1, 2)    # Unigrams + bigrams help
    )),
    ('clf', LogisticRegression(max_iter=1000))
])

# Step 4: Train the model
pipeline.fit(X_train, y_train)

# Step 5: Evaluate
y_pred = pipeline.predict(X_test)
print(classification_report(y_test, y_pred))

# ✅ Step 6: Predict on new transaction data (from your Streamlit app)
# Assume `df` is your parsed dataframe
df["category"] = pipeline.predict(df["clean_description"])

"""
-------------
Use the Model in Streamlit App
-------------
import joblib

@st.cache_resource
def load_classifier():
    return joblib.load("uob_transaction_classifier.pkl")

# Load the model
classifier = load_classifier()

# Predict categories
df_clean["category"] = classifier.predict(df_clean["clean_description"])

-------------
Display Model output in App
-------------
st.subheader("📂 Categorized Transactions")
st.dataframe(df_clean[["date", "clean_description", "category", "withdrawal", "deposit", "balance"]])

"""