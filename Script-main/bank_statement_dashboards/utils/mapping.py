import pandas as pd
import os

# Get the absolute path to the current directory of this file
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING_FILE = os.path.join(CURRENT_DIR, "merchant_category_mapping.csv")

def load_mapping():
    if os.path.exists(MAPPING_FILE):
        mapping_df = pd.read_csv(MAPPING_FILE)
        return dict(zip(mapping_df["Merchant"], mapping_df["Category"]))
    else:
        return {}

def save_mapping(mapping):
    mapping_df = pd.DataFrame(list(mapping.items()), columns=["Merchant", "Category"])
    mapping_df.to_csv(MAPPING_FILE, index=False)