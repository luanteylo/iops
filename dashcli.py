import streamlit as st
import pandas as pd
from pathlib import Path
from sqlalchemy import create_engine
import json
import plotly.express as px


# App title
st.set_page_config(layout="wide")
st.title("📊 IOPS Dashboard")

# --- Step 1: DB path input ---
db_path = Path(st.text_input("Enter path to the SQLite database", value="iops.db"))

if not db_path.exists():
    st.warning("⚠️ Please provide a valid SQLite file path.")
    st.stop()

# Create engine
engine = create_engine(f"sqlite:///{db_path}")

@st.cache_data(ttl=600)
def load_tests_df():
    df =  pd.read_sql("SELECT * FROM Tests WHERE status = 'SUCCESS'", con=engine)
    # breakup the json columns into separate columns adding prefix
    if 'param_json' in df.columns:
        param_json = df['param_json'].apply(json.loads)
        param_df = pd.json_normalize(param_json).add_prefix('param_')
        df = pd.concat([df, param_df], axis=1)
    if 'result_json' in df.columns:
        result_json = df['result_json'].apply(json.loads)
        result_df = pd.json_normalize(result_json).add_prefix('result_')
        df = pd.concat([df, result_df], axis=1)

        # Drop original json columns
        df.drop(columns=['param_hash','param_json', 'result_json'], inplace=True, errors='ignore')
        
    
    return df
 

# Load and show DataFrame
df_tests = load_tests_df()


# print the number of tests found
st.markdown(f"**Number of tests found:** {len(df_tests)}")


# Create a tab for each unique I/O pattern
io_patterns = df_tests["param_io_pattern"].dropna().unique()
tabs = st.tabs([f"I/O Pattern: {p}" for p in io_patterns])

for tab, pattern in zip(tabs, io_patterns):
    with tab:
        st.subheader(f"Details for I/O Pattern: {pattern}")
        pattern_df = df_tests[df_tests["param_io_pattern"] == pattern]        

        
        sweep_params = pattern_df['sweep_param'].dropna().unique()

        for sweep_param in sweep_params:
            st.markdown(f"### Sweep Param: `{sweep_param}`")

            # Get all param columns
            param_cols = [col for col in pattern_df.columns if col.startswith("param_")]

            # Fixed params = all except sweep_param
            fixed_params = [col for col in param_cols if col != f"param_{sweep_param}"]

            # Group by fixed parameters
            grouped = pattern_df.groupby(fixed_params)

            for i, (key, group_df) in enumerate(grouped):
                #if len(group_df[sweep_param].unique()) <= 1:
                #    continue  # skip if sweep param didn't vary

                st.markdown(f"#### Group {i+1} — Fixed Params: `{dict(zip(fixed_params, key))}`")

                fig = px.scatter(
                    group_df,
                    x=f"param_{sweep_param}",
                    y="result_bandwidth",
                    hover_data=param_cols,
                    title=f"Bandwidth vs {sweep_param} (Group {i+1})"
                )
                st.plotly_chart(fig, use_container_width=True)



st.subheader("Tests Table")
st.dataframe(df_tests)