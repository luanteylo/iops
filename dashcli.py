import streamlit as st
import pandas as pd
import json
from pathlib import Path

from iops.analytics.storage import MetricsStorage

# App title
st.set_page_config(layout="wide")
st.title("📊 IOPS Dashboard")

# -- Helpers -- #

def load_tests(execution):
    tests = execution.tests
    st.subheader(f"Tests for Execution ID {execution_id}")
    
    rows = []
    for t in tests:
        row = {
            "test_id": t.test_id,
            "repetition": t.repetition,
            "status": t.status
        }

        try:
            param_dict = json.loads(t.param_json)
            row.update({f"param_{k}": v for k, v in param_dict.items()})
        except:
            row["param_error"] = t.param_json

        try:
            if t.result_json:
                result_dict = json.loads(t.result_json)
                row.update({f"result_{k}": v for k, v in result_dict.items()})
        except:
            row["result_error"] = t.result_json

        rows.append(row)

    df = pd.DataFrame(rows)
    return df


# --- Step 1: DB path input ---
db_path = Path(st.text_input("Enter path to the SQLite database", value="iops.db"))

# Try to initialize the storage
if not Path(db_path).exists():
    st.warning("⚠️ Please provide a valid SQLite file path.")
    st.stop()

# Instantiate storage
storage = MetricsStorage(db_path=db_path, read_only=True)

# --- Step 2: Execution ID input ---
execution_id = st.number_input("Enter Execution ID", min_value=1, step=1)

if execution_id:
    execution = storage.get_execution(execution_id)
    if not execution:
        st.error(f"No execution found with ID {execution_id}")
        st.stop()

    df = load_tests(execution)
   
    st.dataframe(df, use_container_width=True)

    
