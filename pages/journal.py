import streamlit as st
import datetime
import os
import json
import firebase_admin
from firebase_admin import credentials, db
import openai

# ---------------------------------------------------
# Login Check
# ---------------------------------------------------
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.error("You must be logged in to view the Journal page. Please login via the Login page.")
    st.stop()

# Use the logged-in user's username as user_id.
user_id = st.session_state.username

# ---------------------------------------------------
# Firebase & OpenAI Setup
# ---------------------------------------------------
if not firebase_admin._apps:
    firebase_creds_json = os.environ.get("FIREBASE_CREDENTIALS")
    if firebase_creds_json:
        try:
            firebase_creds_dict = json.loads(firebase_creds_json)
        except Exception as e:
            st.error("Error parsing FIREBASE_CREDENTIALS: " + str(e))
        database_url = os.environ.get("FIREBASE_DATABASE_URL")
        if not database_url:
            st.error("FIREBASE_DATABASE_URL environment variable not set!")
        else:
            try:
                cred = credentials.Certificate(firebase_creds_dict)
                firebase_admin.initialize_app(cred, {"databaseURL": database_url})
            except Exception as e:
                st.error("Firebase initialization error: " + str(e))
    else:
        st.error("FIREBASE_CREDENTIALS environment variable not set!")

# Set your OpenAI API key (make sure OPENAI_API_KEY is set in your environment)
openai.api_key = os.environ.get("OPENAI_API_KEY")
if openai.api_key is None:
    st.warning("OpenAI API key is not set in the environment. Summarization will not work.")

# ---------------------------------------------------
# Page Config & Sidebar Navigation
# ---------------------------------------------------
st.set_page_config(
    page_title="Journal - Pulse",
    page_icon="📝",
    layout="centered"
)

# ---------------------------------------------------
# Helper Functions for Journal DB
# ---------------------------------------------------
def get_journal_entry(user_id, date_str):
    """Retrieve the journal entry for the given date from Firebase."""
    ref = db.reference(f"users/{user_id}/journal/{date_str}")
    return ref.get()

def save_journal_entry(user_id, date_str, entry):
    """Save the journal entry (a dict) to Firebase under the given date."""
    ref = db.reference(f"users/{user_id}/journal/{date_str}")
    ref.set(entry)

def fetch_journal_entries(user_id):
    """Fetch all journal entries for the user from Firebase.
       Returns a dict with keys as date strings.
    """
    ref = db.reference(f"users/{user_id}/journal")
    entries = ref.get()
    if not isinstance(entries, dict):
        entries = {}
    return entries

def filter_entries_by_period(entries, period, today):
    """Filter entries by period.
       - period: 'Daily', 'Weekly', or 'Monthly'
       - today: a date object representing today.
    """
    filtered = {}
    for date_str, entry in entries.items():
        try:
            entry_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            continue
        if period == "Daily" and entry_date == today:
            filtered[date_str] = entry
        elif period == "Weekly":
            # Assuming week starts on Monday
            week_start = today - datetime.timedelta(days=today.weekday())
            week_end = week_start + datetime.timedelta(days=6)
            if week_start <= entry_date <= week_end:
                filtered[date_str] = entry
        elif period == "Monthly":
            if entry_date.year == today.year and entry_date.month == today.month:
                filtered[date_str] = entry
    return filtered

def build_entries_text(entries):
    """Convert the entries dictionary into a combined text string for summarization."""
    texts = []
    for date_str in sorted(entries.keys()):
        entry = entries[date_str]
        feeling = entry.get("feeling", "").strip()
        cause = entry.get("cause", "").strip()
        if feeling or cause:
            texts.append(f"On {date_str}:\n- Feeling: {feeling}\n- Possible Cause: {cause}\n")
    return "\n".join(texts)

def get_summary_for_entries(entries_text, period):
    """Call the OpenAI API to generate a motivational summary from the journal entries."""
    if not entries_text.strip():
        return "No journal entries to summarize."
    prompt = (
        f"Please summarize the following journal entries for a {period.lower()} period. "
        "Focus on the emotional tone, the main feelings expressed, and possible underlying causes. "
        "Provide a brief motivational summary that helps me stay positive and focused.\n\n"
        f"{entries_text}"
    )
    try:
        # Using the newer client interface
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a supportive and motivational journaling assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=250
        )
        summary = response.choices[0].message.content.strip()
        return summary
    except Exception as e:
        return f"Error generating summary: {e}"

# ---------------------------------------------------
# MAIN PAGE: Journal Entry Input
# ---------------------------------------------------
st.title("Daily Journal 📝")
today = datetime.date.today()
today_str = today.strftime("%Y-%m-%d")
st.subheader(f"Journal Entry for {today_str}")

# Attempt to load any existing journal entry for today
existing_entry = get_journal_entry(user_id, today_str)
default_feeling = existing_entry.get("feeling", "") if existing_entry else ""
default_cause = existing_entry.get("cause", "") if existing_entry else ""

with st.form("journal_entry_form"):
    st.write("Record your feelings and possible causes below:")
    feeling_input = st.text_area("How are you feeling today?", value=default_feeling, height=120)
    cause_input = st.text_area("What do you think is causing these feelings?", value=default_cause, height=120)
    submitted = st.form_submit_button("Save Journal Entry")
    if submitted:
        entry = {
            "feeling": feeling_input,
            "cause": cause_input,
            "timestamp": datetime.datetime.now().isoformat()
        }
        # If there's an existing summary in the entry, preserve it:
        if existing_entry and "summary" in existing_entry:
            entry["summary"] = existing_entry["summary"]
        save_journal_entry(user_id, today_str, entry)
        st.success(f"Journal entry for {today_str} saved successfully!")

# ---------------------------------------------------
# Journal Summaries Section
# ---------------------------------------------------
st.markdown("---")
st.header("Get Journal Summary")

summary_period = st.radio("Select period to summarize", ["Daily", "Weekly", "Monthly"], index=0)
if st.button("Generate Summary"):
    with st.spinner("Fetching and summarizing your journal entries..."):
        all_entries = fetch_journal_entries(user_id)
        filtered_entries = filter_entries_by_period(all_entries, summary_period, today)
        if not filtered_entries:
            st.info(f"No journal entries found for the selected {summary_period.lower()} period.")
        else:
            entries_text = build_entries_text(filtered_entries)
            summary = get_summary_for_entries(entries_text, summary_period)
            st.subheader(f"{summary_period} Summary")
            st.write(summary)

            # Save the summary to the database if the period is Daily.
            if summary_period == "Daily":
                daily_entry = get_journal_entry(user_id, today_str) or {}
                daily_entry["summary"] = summary
                save_journal_entry(user_id, today_str, daily_entry)
                st.info("Daily summary has been saved to your journal entry.")

# ---------------------------------------------------
# Optional: Display Past Journal Entries (History)
# ---------------------------------------------------
with st.expander("Show Past Journal Entries"):
    all_entries = fetch_journal_entries(user_id)
    if not all_entries:
        st.info("No journal entries recorded yet.")
    else:
        # Sort dates in reverse chronological order
        for date_str in sorted(all_entries.keys(), reverse=True):
            entry = all_entries[date_str]
            st.markdown(f"### {date_str}")
            st.markdown(f"**Feeling:** {entry.get('feeling', 'N/A')}")
            st.markdown(f"**Cause:** {entry.get('cause', 'N/A')}")
            # If a summary exists, display it:
            summary_text = entry.get("summary")
            if summary_text:
                st.markdown(f"{summary_text}")
            st.markdown("---")
