import streamlit as st
import requests
import re
import io
import zipfile
import pandas as pd
from datetime import datetime
import time

# --- Configuration & GraphQL Queries ---
API_URL = "https://api.fireflies.ai/graphql"
PAGE_SIZE = 50

LIST_QUERY = """
query ($skip:Int!, $limit:Int!){
  transcripts(skip:$skip, limit:$limit){
    id title dateString
  }
}
"""

TRANSCRIPT_QUERY = """
query ($id:String!){
  transcript(id:$id){
    sentences{ speaker_name text }
  }
}
"""

# --- Helper Functions ---
def gql(query: str, variables: dict, token: str):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(API_URL, json={"query": query, "variables": variables}, headers=headers, timeout=30)
    r.raise_for_status()
    j = r.json()
    if "errors" in j:
        raise RuntimeError(j["errors"][0]["message"])
    return j["data"]

def clean(name: str) -> str:
    return re.sub(r"[^\w\s.-]", "_", name).strip()[:100] or "untitled"

# --- Streamlit UI Setup ---
st.set_page_config(page_title="Fireflies Downloader", page_icon="🪰", layout="wide")
st.title("Fireflies.ai Custom Bulk Downloader")
st.write("Paste your API token, select exactly which meetings you want, and download them all as a single ZIP file.")

# Initialize session states
if "meetings_df" not in st.session_state:
    st.session_state.meetings_df = None
if "editor_key" not in st.session_state:
    st.session_state.editor_key = 0

# --- Sidebar: Authentication ---
with st.sidebar:
    st.header("🔑 Authentication")
    token = st.text_input("Fireflies API Token:", type="password", help="Get this from your Fireflies integrations dashboard.")
    
    if st.button("Fetch Available Recordings", type="primary"):
        if not token:
            st.error("Please enter an API token first!")
        else:
            with st.spinner("Scanning your Fireflies account..."):
                try:
                    all_transcripts = []
                    skip = 0
                    
                    # Fetching all pages
                    while True:
                        batch = gql(LIST_QUERY, {"skip": skip, "limit": PAGE_SIZE}, token)["transcripts"]
                        if not batch:
                            break
                        all_transcripts.extend(batch)
                        skip += PAGE_SIZE
                    
                    if not all_transcripts:
                        st.warning("No recordings found in this account.")
                    else:
                        # CRITICAL: Force reverse chronological order (Newest first)
                        all_transcripts.sort(key=lambda x: x.get("dateString") or "", reverse=True)
                        
                        # Process into a clean DataFrame
                        data = []
                        for t in all_transcripts:
                            try:
                                timestamp = datetime.fromisoformat(t.get("dateString")).astimezone()
                                date_str = timestamp.strftime("%Y-%m-%d %H:%M")
                            except:
                                date_str = "Unknown Date"
                                
                            data.append({
                                "Select": False,
                                "Time": date_str,      # Clear Column Naming
                                "Subject": t.get("title") or "Untitled Meeting", # Clear Column Naming
                                "ID": t["id"]
                            })
                        
                        st.session_state.meetings_df = pd.DataFrame(data)
                        st.session_state.editor_key += 1 # Reset editor view
                        st.success(f"Found {len(data)} recordings!")
                except Exception as e:
                    st.error(f"Failed to fetch: {str(e)}")

# --- Main Panel: Selection & Download ---
if st.session_state.meetings_df is not None:
    st.subheader("📋 Select Recordings to Download")
    
    col1, col2, _ = st.columns([1, 1, 6])
    with col1:
        if st.button("Select All", use_container_width=True):
            st.session_state.meetings_df["Select"] = True
            st.session_state.editor_key += 1
            st.hybrid_rerun() if hasattr(st, "hybrid_rerun") else st.rerun()
    with col2:
        if st.button("Deselect All", use_container_width=True):
            st.session_state.meetings_df["Select"] = False
            st.session_state.editor_key += 1
            st.hybrid_rerun() if hasattr(st, "hybrid_rerun") else st.rerun()

    # Interactive Table (Shows Select, Time, Subject - hides internal ID)
    edited_df = st.data_editor(
        st.session_state.meetings_df,
        key=f"editor_{st.session_state.editor_key}",
        disabled=["Time", "Subject", "ID"],
        hide_index=True,
        use_container_width=True,
        column_config={"ID": None} # This completely hides the ID column from visual clutter
    )
    
    st.session_state.meetings_df["Select"] = edited_df["Select"]
    selected_rows = edited_df[edited_df["Select"] == True]
    st.write(f"**Selected:** {len(selected_rows)} of {len(edited_df)} meetings")

    # --- Step 3: Bundle and Download ---
    if len(selected_rows) > 0:
        if st.button(f"📥 Prepare ZIP of {len(selected_rows)} Transcripts", type="primary"):
            
            zip_buffer = io.BytesIO()
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for idx, (_, row) in enumerate(selected_rows.iterrows()):
                    tid = row["ID"]
                    title = clean(row["Subject"])
                    date_clean = row["Time"].replace(":", "")
                    
                    status_text.text(f"Fetching ({idx+1}/{len(selected_rows)}): {title}")
                    
                    try:
                        sent_data = gql(TRANSCRIPT_QUERY, {"id": tid}, token)["transcript"]["sentences"]
                        if sent_data:
                            text_content = "\n".join(f"{s['speaker_name']}: {s['text']}" for s in sent_data)
                            filename = f"{date_clean} {title} - {tid}.txt"
                            zip_file.writestr(filename, text_content)
                    except Exception as err:
                        st.warning(f"Skipped '{title}': {str(err)}")
                    
                    progress_bar.progress((idx + 1) / len(selected_rows))
                    time.sleep(0.1) 
            
            status_text.empty()
            progress_bar.empty()
            
            st.success("ZIP Archive Ready!")
            st.download_button(
                label="💾 Download ZIP File",
                data=zip_buffer.getvalue(),
                file_name=f"fireflies_transcripts_{datetime.now().strftime('%Y%m%d')}.zip",
                mime="application/zip",
                use_container_width=True
            )
else:
    st.info("👈 Enter your Fireflies API Token in the sidebar and click 'Fetch Available Recordings' to begin.")
    