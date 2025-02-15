import streamlit as st
import datetime
import os
import calendar
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import hashlib
import base64
import firebase_admin
import openai
import bcrypt
from firebase_admin import credentials, db
import streamlit.components.v1 as components
from cryptography.fernet import Fernet, InvalidToken
import uuid

# -------------------------------
# SET PAGE CONFIGURATION
# -------------------------------
st.set_page_config(
    page_title="Pulse", 
    page_icon="assets/app_icon.png", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# -------------------------------
# INITIALIZE FIREBASE (if needed)
# -------------------------------
if not firebase_admin._apps:
    firebase_creds_json = os.environ.get("FIREBASE_CREDENTIALS")
    database_url = os.environ.get("FIREBASE_DATABASE_URL")
    if firebase_creds_json and database_url:
        try:
            cred = credentials.Certificate(json.loads(firebase_creds_json))
            firebase_admin.initialize_app(cred, {"databaseURL": database_url})
        except Exception as e:
            st.error("Firebase initialization error: " + str(e))
    else:
        st.error("FIREBASE_CREDENTIALS and FIREBASE_DATABASE_URL must be set in the environment.")

# -------------------------------
# SET OPENAI API KEY
# -------------------------------
openai.api_key = os.environ.get("OPENAI_API_KEY")
if openai.api_key is None:
    st.warning("OpenAI API key is not set in the environment. Journal and task summarization will not work.")

# -------------------------------
# SETUP DATA ENCRYPTION (Fernet)
# -------------------------------
data_encryption_key = os.environ.get("DATA_ENCRYPTION_KEY")
if not data_encryption_key:
    st.error("DATA_ENCRYPTION_KEY is not set in the environment. All user data will not be encrypted!")
try:
    fernet = Fernet(data_encryption_key.encode())
except Exception as e:
    st.error("Error initializing encryption: " + str(e))

def encrypt_json(data: dict) -> str:
    json_str = json.dumps(data)
    token = fernet.encrypt(json_str.encode()).decode()
    return token

def decrypt_json(token: str) -> dict:
    try:
        decrypted = fernet.decrypt(token.encode()).decode()
        return json.loads(decrypted)
    except InvalidToken:
        st.error("Error decrypting data. Data may be corrupted or the encryption key is invalid.")
        return {}

def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            encoded = base64.b64encode(img_file.read()).decode()
        return encoded
    except Exception as e:
        st.error(f"Error loading image at {image_path}: {e}")
        return ""

# -------------------------------
# COOKIE MANAGER SETUP
# -------------------------------
from streamlit_cookies_manager import EncryptedCookieManager
cookie_secret = st.secrets.get("general", {}).get("COOKIE_SECRET")
if not cookie_secret:
    st.error("COOKIE_SECRET not found in st.secrets. Please add it to your secrets.toml under [general].")
    st.stop()
cookies = EncryptedCookieManager(prefix="pulse_app", password=cookie_secret)
if not cookies.ready():
    st.stop()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if cookies.get("login_token") and not st.session_state.logged_in:
    st.session_state.logged_in = True
    st.session_state.username = cookies.get("username")

# -------------------------------
# HELPER: Build page header HTML
# -------------------------------
def build_header_html(title: str) -> str:
    base64_img = get_base64_image("assets/app_icon.png")
    return f"""
    <div style="display: flex; align-items: center; margin-bottom: 20px;">
        <img src="data:image/png;base64,{base64_img}" alt="App Icon" style="height: 100px; margin-right: 20px;">
        <h1 style="color: #0096FF; font-size: 32px;">{title}</h1>
    </div>
    """

# =====================================================
# LOGIN & REGISTRATION (Always the FIRST screen)
# =====================================================
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    base64_image = get_base64_image("assets/app_icon.png")
    header_html = f"""
    <div style="display: flex; align-items: center; margin-bottom: 20px;">
        <img src="data:image/png;base64,{base64_image}" alt="App Icon" style="height: 100px; margin-right: 20px;">
        <h1 style="color: #0096FF; font-size: 32px;">Welcome to Pulse Habit Tracking!</h1>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)

    def register_user(username, display_name, hashed_pw):
        ref = db.reference("users/" + username)
        data = ref.get() or {}
        if "credentials" in data:
            return False
        else:
            data["credentials"] = {
                "display_name": display_name,
                "password": hashed_pw
            }
            initial_data = {
                "habits": {}, 
                "goals": {}, 
                "streaks": {}, 
                "journal": {}, 
                "todo": [],
                "habit_colors": {}
            }
            data["data"] = encrypt_json(initial_data)
            ref.set(data)
            return True

    def login_user(username, password):
        ref = db.reference("users/" + username + "/credentials")
        creds = ref.get()
        if creds is None:
            return False, None
        else:
            stored_pw = creds.get("password")
            if stored_pw and bcrypt.checkpw(password.encode(), stored_pw.encode()):
                display_name = creds.get("display_name")
                return True, display_name
            else:
                return False, None

    tab_login, tab_register = st.tabs(["Login", "Register"])

    with tab_register:
        st.subheader("Create an Account")
        username = st.text_input("Username", key="reg_username")
        display_name = st.text_input("Display Name", key="reg_display_name")
        password = st.text_input("Password", type="password", key="reg_password")
        confirm_password = st.text_input("Confirm Password", type="password", key="reg_confirm")
        
        if st.button("Register"):
            if not username or not display_name or not password:
                st.error("Please fill in all fields.")
            elif password != confirm_password:
                st.error("Passwords do not match.")
            else:
                hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                success = register_user(username, display_name, hashed_pw)
                if success:
                    st.success("Account created successfully! Please click the Login tab to login...")
                    st.markdown(
                        """
                        <script>
                        const tabs = window.parent.document.querySelectorAll('button[role="tab"]');
                        if(tabs.length > 0){
                            tabs[0].click();
                        }
                        </script>
                        """, 
                        unsafe_allow_html=True
                    )
                else:
                    st.error("Username already exists. Please choose another.")

    with tab_login:
        st.subheader("Log In")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        
        if st.button("Login"):
            if not username or not password:
                st.error("Please enter both username and password.")
            else:
                success, display_name = login_user(username, password)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.session_state.name = display_name  
                    st.session_state.page = "Pulse"
                    token = str(uuid.uuid4())
                    cookies["login_token"] = token
                    cookies["username"] = username
                    cookies.save()
                    st.success(f"Welcome, {display_name}!")
                else:
                    st.error("Invalid username or password.")
    st.stop()

# =====================================================
# HELPER FUNCTIONS FOR ENCRYPTED USER DATA
# =====================================================
def load_user_data(user_id):
    ref = db.reference(f"users/{user_id}/data")
    encrypted = ref.get()
    if not encrypted:
        data = {
            "habits": {}, 
            "goals": {}, 
            "streaks": {}, 
            "journal": {}, 
            "todo": [],
            "habit_colors": {}
        }
        ref.set(encrypt_json(data))
        return data
    else:
        return decrypt_json(encrypted)

def save_user_data(user_id, data):
    ref = db.reference(f"users/{user_id}/data")
    ref.set(encrypt_json(data))

# =====================================================
# OTHER HELPER FUNCTIONS
# =====================================================
def shift_month(date_obj, delta):
    year = date_obj.year
    month = date_obj.month + delta
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return datetime.date(year, month, 1)

def compute_current_streak(habit_data, today):
    streak = 0
    d = today
    if d.strftime("%Y-%m-%d") not in habit_data:
        d -= datetime.timedelta(days=1)
    while True:
        d_str = d.strftime("%Y-%m-%d")
        if d_str in habit_data and habit_data[d_str] == "succeeded":
            streak += 1
        else:
            break
        d -= datetime.timedelta(days=1)
    return streak

def compute_longest_streak(habit_data, today):
    dates = [
        datetime.datetime.strptime(d_str, "%Y-%m-%d").date() 
        for d_str in habit_data 
        if datetime.datetime.strptime(d_str, "%Y-%m-%d").date() <= today
    ]
    if not dates:
        return 0
    start = min(dates)
    longest = 0
    current = 0
    d = start
    while d <= today:
        d_str = d.strftime("%Y-%m-%d")
        if habit_data.get(d_str) == "succeeded":
            current += 1
        else:
            longest = max(longest, current)
            current = 0
        d += datetime.timedelta(days=1)
    return max(longest, current)

def get_habit_color(habit):
    if "habit_colors" in st.session_state.data:
        if habit in st.session_state.data["habit_colors"]:
            return st.session_state.data["habit_colors"][habit]
    h = hashlib.md5(habit.encode('utf-8')).hexdigest()
    return '#' + h[:6]

def update_streaks_for_habit(user_id, habit, habit_data, today):
    current_streak = compute_current_streak(habit_data, today)
    longest_streak = compute_longest_streak(habit_data, today)
    today_str = today.strftime("%Y-%m-%d")
    data_to_store = {"current": current_streak, "longest": longest_streak, "last_update": today_str}
    if "streaks" not in st.session_state.data:
        st.session_state.data["streaks"] = {}
    st.session_state.data["streaks"][habit] = data_to_store
    save_user_data(user_id, st.session_state.data)

# =====================================================
# JOURNAL FUNCTIONS (using encrypted blob)
# =====================================================
def get_journal_entry(date_str):
    return st.session_state.data["journal"].get(date_str)

def save_journal_entry(date_str, entry):
    st.session_state.data["journal"][date_str] = entry
    save_user_data(user_id, st.session_state.data)

def fetch_journal_entries():
    return st.session_state.data.get("journal", {})

def filter_entries_by_period(entries, period, today):
    filtered = {}
    for date_str, entry in entries.items():
        try:
            entry_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            continue
        if period == "Weekly":
            week_start = today - datetime.timedelta(days=today.weekday())
            week_end = week_start + datetime.timedelta(days=6)
            if week_start <= entry_date <= week_end:
                filtered[date_str] = entry
        elif period == "Monthly":
            if entry_date.year == today.year and entry_date.month == today.month:
                filtered[date_str] = entry
    return filtered

def build_entries_text(entries):
    texts = []
    for date_str in sorted(entries.keys()):
        entry = entries[date_str]
        feeling = entry.get("feeling", "").strip()
        cause = entry.get("cause", "").strip()
        if feeling or cause:
            texts.append(f"On {date_str}:\n- Feeling: {feeling}\n- Possible Cause: {cause}\n")
    return "\n".join(texts)

def get_summary_for_entries(entries_text, period):
    if not entries_text.strip():
        return "No journal entries to summarize."
    prompt = (
        f"Please summarize the following journal entries for a {period.lower()} period. "
        "Focus on the emotional tone, the main feelings expressed, and possible underlying causes. "
        "Write as if you are talking to the user. Provide a brief motivational conclusion. "
        "Do not prepend any heading like 'Summary:'. Only return the summary text.\n\n"
        f"{entries_text}"
    )
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "You are a supportive and motivational journaling assistant."},
                      {"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=250
        )
        summary = response.choices[0].message.content.strip()
        return summary
    except Exception as e:
        return f"Error generating summary: {e}"

# =====================================================
# TASK FUNCTIONS (To Do List)
# =====================================================
def filter_tasks_by_period(tasks, period, today):
    if period == "Daily":
        filtered = []
        for task in tasks:
            if task.get("completed") and task.get("completed_at"):
                completed_date = datetime.datetime.fromisoformat(task["completed_at"]).date()
                if completed_date == today:
                    filtered.append(task)
        return filtered

    if period == "Weekly":
        start = today - datetime.timedelta(days=today.weekday())
        end = start + datetime.timedelta(days=6)
    elif period == "Monthly":
        start = today.replace(day=1)
        end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    else:
        return tasks

    filtered = []
    for task in tasks:
        created_date = datetime.datetime.fromisoformat(task["timestamp"]).date()
        completed_date = None
        if task.get("completed") and task.get("completed_at"):
            completed_date = datetime.datetime.fromisoformat(task["completed_at"]).date()
        if task.get("completed") and completed_date and start <= completed_date <= end:
            filtered.append(task)
        elif not task.get("completed") and start <= created_date <= end:
            filtered.append(task)
    return filtered

def get_grouped_tasks_summary(tasks):
    if not tasks:
        return ""
    grouped_tasks = {}
    for task in tasks:
        if task.get("completed") and task.get("completed_at"):
            try:
                completed_date = datetime.datetime.fromisoformat(task["completed_at"]).date()
            except Exception:
                continue
            date_str = completed_date.strftime("%Y-%m-%d")
            grouped_tasks.setdefault(date_str, []).append(task["task"])
    summary_text = ""
    for date_str in sorted(grouped_tasks.keys(), reverse=True):
        summary_text += f"Tasks completed on {date_str}: " + ", ".join(grouped_tasks[date_str]) + "\n"
    return summary_text

def get_ai_tasks_summary(grouped_text, period):
    if not grouped_text.strip():
        return f"No tasks completed this {period.lower()}."
    prompt = (
        f"Based on the following log of tasks completed during the {period.lower()} period, "
        "please provide a summary that highlights what was accomplished and offers an encouraging message. "
        "Only return the summary text without any additional formatting or headings.\n\n"
        f"{grouped_text}"
    )
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "You are a motivational productivity assistant."},
                      {"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=250
        )
        summary = response.choices[0].message.content.strip()
        return summary
    except Exception as e:
        return f"Error generating summary: {e}"

# =====================================================
# LOAD USER DATA & INITIALIZE SESSION STATE
# =====================================================
user_id = st.session_state.username
if "data" not in st.session_state:
    st.session_state.data = load_user_data(user_id)
if "tracker_month" not in st.session_state:
    st.session_state.tracker_month = datetime.date.today().replace(day=1)
if "tracker_week" not in st.session_state:
    today = datetime.date.today()
    st.session_state.tracker_week = today - datetime.timedelta(days=today.weekday())
# Initialize tracker_year for yearly analytics
if "tracker_year" not in st.session_state:
    st.session_state.tracker_year = datetime.date.today().replace(month=1, day=1)

today = datetime.date.today()
today_str = today.strftime("%Y-%m-%d")

# Update streaks for each habit
for habit in st.session_state.data["habits"]:
    update_streaks_for_habit(user_id, habit, st.session_state.data["habits"][habit], today)

# -----------------------------------------------------
# Place "Logged in as {username}" and "Logout" on the right
# -----------------------------------------------------
top_col_left, top_col_right = st.columns([0.8, 0.2])
with top_col_right:
    st.markdown(f"**Logged in as {user_id}**")
    if st.button("Logout"):
        st.session_state.logged_in = False
        cookies["login_token"] = ""
        cookies["username"] = ""
        cookies.save()
        if hasattr(st, "experimental_rerun"):
            st.experimental_rerun()
        else:
            st.stop()

# =====================================================
# CREATE TOP TABS
# =====================================================
tab_pulse, tab_analytics, tab_journal, tab_todo = st.tabs([
    "Weekly Habit Tracker 📆", 
    "Analytics 📊", 
    "Well-Being Journal 🗒️",
    "To-Do List ✅"
])

# =====================================================
# TAB: PULSE (Main Habit Tracker)
# =====================================================
with tab_pulse:
    components.html(build_header_html("Pulse Weekly Habit Tracker"), height=150)

    # --- Manage Habits ---
    with st.expander("Manage Habits", expanded=False):
        st.subheader("Add Habit")
        new_habit = st.text_input("Habit", key="new_habit_input")
        new_goal = st.number_input("Set Weekly Goal (# times you would like to hit the target per week)", min_value=1, value=1, key="new_goal_input")
        new_color = st.color_picker("Pick a color", value="#000000", key="new_color_input")

        if st.button("Add Habit", key="add_habit_button"):
            new_habit = new_habit.strip()
            if not new_habit:
                st.error("Please enter a valid habit.")
            elif new_habit in st.session_state.data["habits"]:
                st.error("This habit already exists!")
            else:
                st.session_state.data["habits"][new_habit] = {}
                st.session_state.data["goals"][new_habit] = int(new_goal)
                if "habit_colors" not in st.session_state.data:
                    st.session_state.data["habit_colors"] = {}
                st.session_state.data["habit_colors"][new_habit] = new_color

                update_streaks_for_habit(user_id, new_habit, st.session_state.data["habits"][new_habit], today)
                save_user_data(user_id, st.session_state.data)
                st.success(f"Habit '{new_habit}' added successfully!")
                # Clear the input fields and re-run if possible
                st.session_state["new_habit_input"] = ""
                st.session_state["new_goal_input"] = 1
                st.session_state["new_color_input"] = "#000000"
                if hasattr(st, "experimental_rerun"):
                    st.experimental_rerun()

        st.subheader("Manage Habits")
        if st.session_state.data["habits"]:
            habits_list = list(st.session_state.data["habits"].keys())
            for habit in habits_list:
                current_goal = int(st.session_state.data["goals"].get(habit, 0))

                col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 1, 1])
                new_name_val = col1.text_input("Habit name", value=habit, key=f"edit_habit_name_{habit}")
                new_goal_val = col2.number_input(
                    "Weekly goal", 
                    min_value=1, 
                    value=current_goal, 
                    key=f"edit_goal_{habit}"
                )
                current_color = "#000000"
                if "habit_colors" in st.session_state.data and habit in st.session_state.data["habit_colors"]:
                    current_color = st.session_state.data["habit_colors"][habit]
                new_color_val = col3.color_picker(
                    "Color", 
                    value=current_color, 
                    key=f"edit_color_{habit}"
                )

                if col4.button("Update", key=f"update_goal_{habit}"):
                    if new_name_val != habit:
                        st.session_state.data["habits"][new_name_val] = st.session_state.data["habits"].pop(habit)
                        st.session_state.data["goals"][new_name_val] = st.session_state.data["goals"].pop(habit)
                        if "streaks" in st.session_state.data and habit in st.session_state.data["streaks"]:
                            st.session_state.data["streaks"][new_name_val] = st.session_state.data["streaks"].pop(habit)
                        if "habit_colors" in st.session_state.data and habit in st.session_state.data["habit_colors"]:
                            st.session_state.data["habit_colors"][new_name_val] = st.session_state.data["habit_colors"].pop(habit)
                        habit = new_name_val

                    st.session_state.data["goals"][habit] = int(new_goal_val)
                    if "habit_colors" not in st.session_state.data:
                        st.session_state.data["habit_colors"] = {}
                    st.session_state.data["habit_colors"][habit] = new_color_val
                    save_user_data(user_id, st.session_state.data)
                    st.success(f"Updated habit '{habit}' successfully!")

                if col5.button("Remove", key=f"remove_{habit}"):
                    st.session_state.data["habits"].pop(habit, None)
                    st.session_state.data["goals"].pop(habit, None)
                    if "streaks" in st.session_state.data and habit in st.session_state.data["streaks"]:
                        st.session_state.data["streaks"].pop(habit, None)
                    if "habit_colors" in st.session_state.data and habit in st.session_state.data["habit_colors"]:
                        st.session_state.data["habit_colors"].pop(habit, None)
                    save_user_data(user_id, st.session_state.data)
                    st.success(f"Habit '{habit}' removed successfully!")
                    if hasattr(st, "experimental_rerun"):
                        st.experimental_rerun()
                    else:
                        st.stop()
        else:
            st.info("You currently have no habits you are tracking. Please add one above.")

    # --- Weekly Habit Tracker Grid ---
    if st.session_state.data["habits"]:
        week_start = today - datetime.timedelta(days=today.weekday())
        week_dates = [week_start + datetime.timedelta(days=i) for i in range(7)]

        st.markdown('<div class="calendar-container">', unsafe_allow_html=True)
        header_cols = st.columns(10)
        header_cols[0].markdown("**Habit**")
        for i, d in enumerate(week_dates):
            header_cols[i+1].markdown(f"**{d.strftime('%a')}**")
        header_cols[8].markdown("**Current Streak**")
        header_cols[9].markdown("**Longest Streak**")

        habits = list(st.session_state.data["habits"].keys())
        for habit in habits:
            row_cols = st.columns(10)
            color = get_habit_color(habit)
            row_cols[0].markdown(f"**<span style='color:{color}'>{habit}</span>**", unsafe_allow_html=True)
            
            for i, current_date in enumerate(week_dates):
                date_str = current_date.strftime("%Y-%m-%d")
                outcome = st.session_state.data["habits"][habit].get(date_str, None)
                label = "✅" if outcome == "succeeded" else "❌" if outcome == "failed" else str(current_date.day)
                if row_cols[i+1].button(label, key=f"weekly_{habit}_{date_str}"):
                    current_outcome = st.session_state.data["habits"][habit].get(date_str, None)
                    new = None
                    if current_outcome is None:
                        new = "succeeded"
                    elif current_outcome == "succeeded":
                        new = "failed"
                    if new is None:
                        st.session_state.data["habits"][habit].pop(date_str, None)
                    else:
                        st.session_state.data["habits"][habit][date_str] = new

                    save_user_data(user_id, st.session_state.data)
                    update_streaks_for_habit(user_id, habit, st.session_state.data["habits"][habit], today)

            streak_data = st.session_state.data.get("streaks", {}).get(habit, {})
            current_streak = streak_data.get("current", 0)
            longest_streak = streak_data.get("longest", 0)
            row_cols[8].markdown(f"**{current_streak}**")
            row_cols[9].markdown(f"**{longest_streak}**")

        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("You currently have no habits to display on the weekly tracker. Please add one under 'Manage Habits'.")

# =====================================================
# TAB: ANALYTICS (Habit Tracking Analytics)
# =====================================================
with tab_analytics:
    components.html(build_header_html("Pulse Analytics"), height=150)
    
    # Build a dataframe of successes
    records = []
    for habit, days_dict in st.session_state.data["habits"].items():
        for date_str, outcome in days_dict.items():
            if outcome == "succeeded":
                try:
                    date_obj = pd.to_datetime(date_str)
                    records.append({"habit": habit, "date": date_obj})
                except Exception:
                    pass
    if records:
        df = pd.DataFrame(records)
    else:
        df = pd.DataFrame(columns=["habit", "date"])

    analytics_tabs = st.tabs(["Weekly", "Monthly", "Yearly"])
    
    # ----------------- WEEKLY ANALYTICS -----------------
    with analytics_tabs[0]:
        current_week_start = st.session_state.tracker_week
        current_week_end = current_week_start + datetime.timedelta(days=6)

        col_prev, col_center, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("◀ Previous Week", key="prev_week"):
                st.session_state.tracker_week -= datetime.timedelta(days=7)
        with col_center:
            st.markdown(f"### Week of {current_week_start.strftime('%Y-%m-%d')}")
        with col_next:
            if st.button("Next Week ▶", key="next_week"):
                st.session_state.tracker_week += datetime.timedelta(days=7)

        last_week_start = current_week_start - datetime.timedelta(days=7)
        last_week_end = current_week_start - datetime.timedelta(days=1)

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            mask_current = (df["date"].dt.date >= current_week_start) & (df["date"].dt.date <= current_week_end)
            mask_last = (df["date"].dt.date >= last_week_start) & (df["date"].dt.date <= last_week_end)
            df_current = df[mask_current]
            df_last = df[mask_last]
        else:
            df_current = pd.DataFrame(columns=["habit", "date"])
            df_last = pd.DataFrame(columns=["habit", "date"])

        current_summary = df_current.groupby("habit").size().reset_index(name="current_success_count")
        last_summary = df_last.groupby("habit").size().reset_index(name="last_success_count")

        for habit in st.session_state.data["habits"].keys():
            if habit not in current_summary["habit"].values:
                current_summary = pd.concat([current_summary, pd.DataFrame([{"habit": habit, "current_success_count": 0}])], ignore_index=True)
            if habit not in last_summary["habit"].values:
                last_summary = pd.concat([last_summary, pd.DataFrame([{"habit": habit, "last_success_count": 0}])], ignore_index=True)

        summary_compare = pd.merge(current_summary, last_summary, on="habit", how="outer").fillna(0)
        summary_compare["current_success_count"] = summary_compare["current_success_count"].astype(int)
        summary_compare["last_success_count"] = summary_compare["last_success_count"].astype(int)
        summary_compare["goal"] = summary_compare["habit"].apply(lambda h: int(st.session_state.data["goals"].get(h, 0)))

        cols = st.columns(3)
        sorted_compare = summary_compare.sort_values("habit").reset_index(drop=True)
        for idx, row in sorted_compare.iterrows():
            habit = row["habit"]
            goal_val = row["goal"]
            delta_str = f"{row['current_success_count'] - row['last_success_count']:+}" if row["last_success_count"] > 0 else "N/A"
            current_pct = (row["current_success_count"] / goal_val * 100) if goal_val > 0 else 0
            value_str = f"{row['current_success_count']} / {goal_val} ({int(current_pct)}%)"
            col = cols[idx % 3]
            col.metric(label=habit, value=value_str, delta=delta_str)

        weekly_sub_tabs = st.tabs(["Progress Bar Chart", "Progress Heatmap"])
        
        # --- WEEKLY BAR CHART ---
        with weekly_sub_tabs[0]:
            melt_compare = summary_compare.melt(
                id_vars="habit", 
                value_vars=["current_success_count", "last_success_count", "goal"],
                var_name="Metric", 
                value_name="Count"
            )
            melt_compare["Metric"] = melt_compare["Metric"].map({
                "current_success_count": "Current Week",
                "last_success_count": "Last Week",
                "goal": "Goal"
            })
            fig_compare = px.bar(
                melt_compare,
                x="habit",
                y="Count",
                color="Metric",
                barmode="group",
                color_discrete_map={
                    "Current Week": "#64b5f6",
                    "Last Week": "#0d47a1",
                    "Goal": "#2E7D32"
                },
                template="plotly_white"
            )
            st.plotly_chart(fig_compare, use_container_width=True, key="weekly_bar_chart")

        # --- WEEKLY HEATMAP ---
        with weekly_sub_tabs[1]:
            week_dates = [current_week_start + datetime.timedelta(days=i) for i in range(7)]
            heatmap_data_weekly = []
            hover_data_weekly = []
            display_data_weekly = []

            for habit in st.session_state.data["habits"].keys():
                row = []
                hover_row = []
                display_row = []
                for day in week_dates:
                    day_str = day.strftime("%Y-%m-%d")
                    outcome = st.session_state.data["habits"][habit].get(day_str)
                    if outcome == "succeeded":
                        val = 2
                        hover_txt = f"{day_str}: Succeeded"
                        disp_txt = "✓"
                    elif outcome == "failed":
                        val = 1
                        hover_txt = f"{day_str}: Failed"
                        disp_txt = "X"
                    else:
                        val = 0
                        hover_txt = f"{day_str}: No Data"
                        disp_txt = " "
                    row.append(val)
                    hover_row.append(hover_txt)
                    display_row.append(disp_txt)
                heatmap_data_weekly.append(row)
                hover_data_weekly.append(hover_row)
                display_data_weekly.append(display_row)

            fig_heatmap_weekly = go.Figure(data=go.Heatmap(
                z=heatmap_data_weekly,
                x=[day.strftime("%a") for day in week_dates],
                y=list(st.session_state.data["habits"].keys()),
                text=display_data_weekly,
                texttemplate="%{text}",
                hovertext=hover_data_weekly,
                hoverinfo="text",
                colorscale=[
                    [0.0, "#eaeaea"],
                    [0.5, "#FF0000"],
                    [1.0, "#4BB543"]
                ],
                zmin=0,
                zmax=2,
                showscale=False,
                xgap=3,
                ygap=3
            ))
            fig_heatmap_weekly.update_layout(
                xaxis=dict(showgrid=False), 
                yaxis=dict(showgrid=False), 
                template="plotly_white"
            )
            st.plotly_chart(fig_heatmap_weekly, use_container_width=True, key="weekly_heatmap_chart")

    # ----------------- MONTHLY ANALYTICS -----------------
    with analytics_tabs[1]:
        current_month_start = st.session_state.tracker_month
        year = current_month_start.year
        month = current_month_start.month
        num_days = calendar.monthrange(year, month)[1]
        current_month_end = datetime.date(year, month, num_days)

        col_prev, col_center, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("◀ Previous Month", key="prev_month"):
                st.session_state.tracker_month = shift_month(current_month_start, -1)
        with col_center:
            st.markdown(f"### {current_month_start.strftime('%B %Y')}")
        with col_next:
            if st.button("Next Month ▶", key="next_month"):
                st.session_state.tracker_month = shift_month(current_month_start, 1)

        prev_month_start = shift_month(current_month_start, -1)
        prev_year = prev_month_start.year
        prev_month = prev_month_start.month
        prev_num_days = calendar.monthrange(prev_year, prev_month)[1]
        prev_month_end = datetime.date(prev_year, prev_month, prev_num_days)

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            mask_current = (df["date"].dt.date >= current_month_start) & (df["date"].dt.date <= current_month_end)
            mask_prev = (df["date"].dt.date >= prev_month_start) & (df["date"].dt.date <= prev_month_end)
            df_current = df[mask_current]
            df_prev = df[mask_prev]
        else:
            df_current = pd.DataFrame(columns=["habit", "date"])
            df_prev = pd.DataFrame(columns=["habit", "date"])

        current_summary = df_current.groupby("habit").size().reset_index(name="current_success_count")
        prev_summary = df_prev.groupby("habit").size().reset_index(name="prev_success_count")

        for habit in st.session_state.data["habits"].keys():
            if habit not in current_summary["habit"].values:
                current_summary = pd.concat([current_summary, pd.DataFrame([{"habit": habit, "current_success_count": 0}])], ignore_index=True)
            if habit not in prev_summary["habit"].values:
                prev_summary = pd.concat([prev_summary, pd.DataFrame([{"habit": habit, "prev_success_count": 0}])], ignore_index=True)

        summary_compare = pd.merge(current_summary, prev_summary, on="habit", how="outer").fillna(0)
        summary_compare["current_success_count"] = summary_compare["current_success_count"].astype(int)
        summary_compare["prev_success_count"] = summary_compare["prev_success_count"].astype(int)

        summary_compare["goal"] = summary_compare["habit"].apply(
            lambda h: int(st.session_state.data["goals"].get(h, 0) / 7 * num_days)
        )

        cols = st.columns(3)
        sorted_compare = summary_compare.sort_values("habit").reset_index(drop=True)
        for idx, row in sorted_compare.iterrows():
            habit = row["habit"]
            goal_val = row["goal"]
            delta_str = f"{row['current_success_count'] - row['prev_success_count']:+}" if row["prev_success_count"] > 0 else "N/A"
            current_pct = (row["current_success_count"] / goal_val * 100) if goal_val > 0 else 0
            value_str = f"{row['current_success_count']} / {goal_val} ({int(current_pct)}%)"
            col = cols[idx % 3]
            col.metric(label=habit, value=value_str, delta=delta_str)

        monthly_sub_tabs = st.tabs(["Progress Bar Chart", "Progress Heatmap"])
        
        # --- MONTHLY BAR CHART ---
        with monthly_sub_tabs[0]:
            melt_compare = summary_compare.melt(
                id_vars="habit", 
                value_vars=["current_success_count", "prev_success_count", "goal"],
                var_name="Metric", 
                value_name="Count"
            )
            melt_compare["Metric"] = melt_compare["Metric"].map({
                "current_success_count": "Current Month",
                "prev_success_count": "Previous Month",
                "goal": "Goal"
            })
            fig_compare = px.bar(
                melt_compare,
                x="habit",
                y="Count",
                color="Metric",
                barmode="group",
                color_discrete_map={
                    "Current Month": "#64b5f6",
                    "Previous Month": "#0d47a1",
                    "Goal": "#2E7D32"
                },
                template="plotly_white"
            )
            st.plotly_chart(fig_compare, use_container_width=True, key="monthly_bar_chart")

        # --- MONTHLY HEATMAP ---
        with monthly_sub_tabs[1]:
            days = [datetime.date(year, month, d) for d in range(1, num_days+1)]
            heatmap_data = []
            hover_data = []
            display_data = []

            for habit in st.session_state.data["habits"].keys():
                row = []
                hover_row = []
                disp_row = []
                for day in days:
                    day_str = day.strftime("%Y-%m-%d")
                    outcome = st.session_state.data["habits"][habit].get(day_str)
                    if outcome == "succeeded":
                        val = 2
                        hover_txt = f"{day_str}: Succeeded"
                        disp_txt = "✓"
                    elif outcome == "failed":
                        val = 1
                        hover_txt = f"{day_str}: Failed"
                        disp_txt = "X"
                    else:
                        val = 0
                        hover_txt = f"{day_str}: No Data"
                        disp_txt = " "
                    row.append(val)
                    hover_row.append(hover_txt)
                    disp_row.append(disp_txt)
                heatmap_data.append(row)
                hover_data.append(hover_row)
                display_data.append(disp_row)

            fig_heatmap = go.Figure(data=go.Heatmap(
                z=heatmap_data,
                x=[str(day.day) for day in days],
                y=list(st.session_state.data["habits"].keys()),
                text=display_data,
                texttemplate="%{text}",
                hovertext=hover_data,
                hoverinfo="text",
                colorscale=[
                    [0.0, "#eaeaea"],
                    [0.5, "#FF0000"],
                    [1.0, "#4BB543"]
                ],
                zmin=0,
                zmax=2,
                showscale=False,
                xgap=3,
                ygap=3
            ))
            fig_heatmap.update_layout(
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=False),
                template="plotly_white"
            )
            st.plotly_chart(fig_heatmap, use_container_width=True, key="monthly_heatmap_chart")

    # ----------------- YEARLY ANALYTICS -----------------
    with analytics_tabs[2]:
        current_year_start = st.session_state.tracker_year
        current_year = current_year_start.year
        # Determine if it's a leap year
        year_length = 366 if calendar.isleap(current_year) else 365
        current_year_end = datetime.date(current_year, 12, 31)

        col_prev, col_center, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("◀ Previous Year", key="prev_year"):
                st.session_state.tracker_year = datetime.date(current_year - 1, 1, 1)
        with col_center:
            st.markdown(f"### {current_year}")
        with col_next:
            if st.button("Next Year ▶", key="next_year"):
                st.session_state.tracker_year = datetime.date(current_year + 1, 1, 1)

        prev_year = current_year - 1
        prev_year_start = datetime.date(prev_year, 1, 1)
        prev_year_end = datetime.date(prev_year, 12, 31)

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            mask_current = (df["date"].dt.date >= current_year_start) & (df["date"].dt.date <= current_year_end)
            mask_prev = (df["date"].dt.date >= prev_year_start) & (df["date"].dt.date <= prev_year_end)
            df_current = df[mask_current]
            df_prev = df[mask_prev]
        else:
            df_current = pd.DataFrame(columns=["habit", "date"])
            df_prev = pd.DataFrame(columns=["habit", "date"])

        current_summary = df_current.groupby("habit").size().reset_index(name="current_success_count")
        prev_summary = df_prev.groupby("habit").size().reset_index(name="prev_success_count")

        for habit in st.session_state.data["habits"].keys():
            if habit not in current_summary["habit"].values:
                current_summary = pd.concat([current_summary, pd.DataFrame([{"habit": habit, "current_success_count": 0}])], ignore_index=True)
            if habit not in prev_summary["habit"].values:
                prev_summary = pd.concat([prev_summary, pd.DataFrame([{"habit": habit, "prev_success_count": 0}])], ignore_index=True)

        summary_compare = pd.merge(current_summary, prev_summary, on="habit", how="outer").fillna(0)
        summary_compare["current_success_count"] = summary_compare["current_success_count"].astype(int)
        summary_compare["prev_success_count"] = summary_compare["prev_success_count"].astype(int)
        # Estimate yearly goal based on weekly goal scaled to the year
        summary_compare["goal"] = summary_compare["habit"].apply(
            lambda h: int(st.session_state.data["goals"].get(h, 0) / 7 * year_length)
        )

        cols = st.columns(3)
        sorted_compare = summary_compare.sort_values("habit").reset_index(drop=True)
        for idx, row in sorted_compare.iterrows():
            habit = row["habit"]
            goal_val = row["goal"]
            delta_str = f"{row['current_success_count'] - row['prev_success_count']:+}" if row["prev_success_count"] > 0 else "N/A"
            current_pct = (row["current_success_count"] / goal_val * 100) if goal_val > 0 else 0
            value_str = f"{row['current_success_count']} / {goal_val} ({int(current_pct)}%)"
            col = cols[idx % 3]
            col.metric(label=habit, value=value_str, delta=delta_str)

        yearly_sub_tabs = st.tabs(["Progress Bar Chart", "Progress Heatmap"])
        
        # --- YEARLY BAR CHART ---
        with yearly_sub_tabs[0]:
            melt_compare = summary_compare.melt(
                id_vars="habit", 
                value_vars=["current_success_count", "prev_success_count", "goal"],
                var_name="Metric", 
                value_name="Count"
            )
            melt_compare["Metric"] = melt_compare["Metric"].map({
                "current_success_count": "Current Year",
                "prev_success_count": "Previous Year",
                "goal": "Goal"
            })
            fig_compare = px.bar(
                melt_compare,
                x="habit",
                y="Count",
                color="Metric",
                barmode="group",
                color_discrete_map={
                    "Current Year": "#64b5f6",
                    "Previous Year": "#0d47a1",
                    "Goal": "#2E7D32"
                },
                template="plotly_white"
            )
            st.plotly_chart(fig_compare, use_container_width=True, key="yearly_bar_chart")

        # --- YEARLY HEATMAP ---
        # For the yearly heatmap, we aggregate monthly successes for each habit.
        with yearly_sub_tabs[1]:
            month_names = [calendar.month_abbr[m] for m in range(1, 13)]
            heatmap_data_yearly = []
            hover_data_yearly = []
            for habit in st.session_state.data["habits"].keys():
                monthly_counts = []
                monthly_hover = []
                for m in range(1, 13):
                    # Get the number of successes in month m of the current year
                    start_date = datetime.date(current_year, m, 1)
                    end_day = calendar.monthrange(current_year, m)[1]
                    end_date = datetime.date(current_year, m, end_day)
                    mask = (df["date"].dt.date >= start_date) & (df["date"].dt.date <= end_date)
                    habit_mask = df[mask]["habit"] == habit
                    count = df[mask][habit_mask].shape[0]
                    monthly_counts.append(count)
                    monthly_hover.append(f"{month_names[m-1]}: {count} successes")
                heatmap_data_yearly.append(monthly_counts)
                hover_data_yearly.append(monthly_hover)
            
            fig_heatmap_yearly = go.Figure(data=go.Heatmap(
                z=heatmap_data_yearly,
                x=month_names,
                y=list(st.session_state.data["habits"].keys()),
                text=heatmap_data_yearly,
                hovertext=hover_data_yearly,
                hoverinfo="text",
                colorscale="Greens",
                zmin=0,
                zmax=28,
                showscale=False
            ))
            fig_heatmap_yearly.update_layout(
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=False),
                template="plotly_white"
            )
            st.plotly_chart(fig_heatmap_yearly, use_container_width=True, key="yearly_heatmap_chart")

# =====================================================
# TAB: JOURNAL (Well Being Journal)
# =====================================================
with tab_journal:
    components.html(build_header_html("Pulse Well-Being Journal"), height=150)

    journal_main_tabs = st.tabs(["Journal Entry", "Journal Summary", "Journal Entries"])

    # ---------------- JOURNAL ENTRY ----------------
    with journal_main_tabs[0]:
        today = datetime.date.today()
        today_str = today.strftime("%Y-%m-%d")
        st.subheader(f"Journal Entry for Today")

        existing_entry = get_journal_entry(today_str)
        default_feeling = existing_entry.get("feeling", "") if existing_entry else ""
        default_cause = existing_entry.get("cause", "") if existing_entry else ""
        daily_summary = existing_entry.get("summary") if existing_entry else None

        with st.form("journal_entry_form"):
            feeling_input = st.text_area("How are you feeling today?", value=default_feeling, height=120)
            cause_input = st.text_area("What do you think is causing these feelings?", value=default_cause, height=120)
            submitted = st.form_submit_button("Save Journal Entry")

            if submitted:
                entry = {
                    "feeling": feeling_input, 
                    "cause": cause_input, 
                    "timestamp": datetime.datetime.now().isoformat()
                }
                st.success(f"Journal entry for {today_str} saved successfully!")

                if feeling_input.strip() or cause_input.strip():
                    entries_text = build_entries_text({today_str: entry})
                    daily_summary = get_summary_for_entries(entries_text, "Daily")
                    entry["summary"] = daily_summary

                save_journal_entry(today_str, entry)

        if daily_summary:
            st.subheader("Auto-Generated Daily Summary")
            st.write(daily_summary)

    # ---------------- JOURNAL SUMMARY ----------------
    with journal_main_tabs[1]:
        journal_summary_tabs = st.tabs(["Weekly", "Monthly"])

        with journal_summary_tabs[0]:
            if st.button("Generate Weekly Well-Being Summary", key="weekly_summary"):
                with st.spinner("Fetching and summarizing your journal entries..."):
                    all_entries = fetch_journal_entries()
                    filtered_entries = filter_entries_by_period(all_entries, "Weekly", today)
                    if not filtered_entries:
                        st.info("No journal entries found for this week.")
                    else:
                        entries_text = build_entries_text(filtered_entries)
                        summary = get_summary_for_entries(entries_text, "Weekly")
                        st.write(summary)

        with journal_summary_tabs[1]:
            if st.button("Generate Monthly Well-Being Summary", key="monthly_summary"):
                with st.spinner("Fetching and summarizing your journal entries..."):
                    all_entries = fetch_journal_entries()
                    filtered_entries = filter_entries_by_period(all_entries, "Monthly", today)
                    if not filtered_entries:
                        st.info("No journal entries found for this month.")
                    else:
                        entries_text = build_entries_text(filtered_entries)
                        summary = get_summary_for_entries(entries_text, "Monthly")
                        st.write(summary)

    # ---------------- PAST JOURNAL ENTRIES ----------------
    with journal_main_tabs[2]:
        all_entries = fetch_journal_entries()
        if not all_entries:
            st.info("No journal entries recorded yet.")
        else:
            for date_str in sorted(all_entries.keys(), reverse=True):
                entry = all_entries[date_str]
                st.markdown(f"### **{date_str}**")
                st.markdown(f"**Feeling:** {entry.get('feeling', 'N/A')}")
                st.markdown(f"**Cause:** {entry.get('cause', 'N/A')}")
                summary_text = entry.get("summary")
                if summary_text:
                    st.markdown("#### Auto-Generated Summary")
                    st.markdown(summary_text)
                st.markdown("---")

# =====================================================
# TAB: TO DO LIST
# =====================================================
with tab_todo:
    components.html(build_header_html("Pulse To-Do List"), height=150)

    todo_main_tabs = st.tabs(["To-Do List", "Completed Task Summary", "Completed Tasks Breakdown"])

    # ------------------- TASKS -------------------
    with todo_main_tabs[0]:
        st.subheader("Your To-Do List")
        # Use a form so the input clears automatically on submission
        with st.form("todo_form"):
            new_task = st.text_input("Enter a new task", key="new_todo_task")
            submit_task = st.form_submit_button("Add Task")
            if submit_task:
                if new_task.strip() == "":
                    st.error("Please enter a valid task.")
                else:
                    if "todo" not in st.session_state.data:
                        st.session_state.data["todo"] = []
                    task_obj = {
                        "id": str(uuid.uuid4()),
                        "task": new_task.strip(),
                        "completed": False,
                        "timestamp": datetime.datetime.now().isoformat(),
                        "completed_at": None
                    }
                    st.session_state.data["todo"].append(task_obj)
                    save_user_data(user_id, st.session_state.data)
                    st.success("Task added successfully!")
                    if hasattr(st, "experimental_rerun"):
                        st.experimental_rerun()

        st.markdown("---")
        if "todo" in st.session_state.data and st.session_state.data["todo"]:
            for task in st.session_state.data["todo"]:
                col1, col2, col3 = st.columns([6, 1, 1])
                new_completed = col1.checkbox(task["task"], value=task.get("completed", False), key=task["id"])
                if new_completed != task.get("completed", False):
                    task["completed"] = new_completed
                    if new_completed:
                        task["completed_at"] = datetime.datetime.now().isoformat()
                    else:
                        task["completed_at"] = None
                    save_user_data(user_id, st.session_state.data)

                if col2.button("Delete", key="del_" + task["id"]):
                    st.session_state.data["todo"].remove(task)
                    save_user_data(user_id, st.session_state.data)
                    if hasattr(st, "experimental_rerun"):
                        st.experimental_rerun()
                    else:
                        st.stop()
        else:
            st.info("No tasks added yet. You can add one by entering a new task above!")

        st.markdown("---")
        st.subheader("Auto-Generated Daily Completed Tasks Summary")
        completed_today = filter_tasks_by_period(st.session_state.data["todo"], "Daily", today)
        if completed_today:
            grouped_text = get_grouped_tasks_summary(completed_today)
            daily_summary = get_ai_tasks_summary(grouped_text, "Daily")
            st.write(daily_summary)
        else:
            st.info("No tasks completed today. Remember to set some time aside to work on your goals!")

    # ------------------- COMPLETED TASK SUMMARY -------------------
    with todo_main_tabs[1]:
        summary_tabs = st.tabs(["Weekly", "Monthly"])

        with summary_tabs[0]:
            if st.button("Generate Completed Weekly Task Summary", key="weekly_todo_summary"):
                with st.spinner("Generating your weekly task summary..."):
                    tasks_filtered = filter_tasks_by_period(st.session_state.data["todo"], "Weekly", today)
                    if not tasks_filtered:
                        st.info("No tasks completed this week.")
                    else:
                        grouped_text = get_grouped_tasks_summary(tasks_filtered)
                        summary = get_ai_tasks_summary(grouped_text, "Weekly")
                        st.write(summary)

        with summary_tabs[1]:
            if st.button("Generate Completed Monthly Task Summary", key="monthly_todo_summary"):
                with st.spinner("Generating your monthly task summary..."):
                    tasks_filtered = filter_tasks_by_period(st.session_state.data["todo"], "Monthly", today)
                    if not tasks_filtered:
                        st.info("No tasks completed this month.")
                    else:
                        grouped_text = get_grouped_tasks_summary(tasks_filtered)
                        summary = get_ai_tasks_summary(grouped_text, "Monthly")
                        st.write(summary)

    # ------------------- COMPLETED TASKS BY DATE -------------------
    with todo_main_tabs[2]:
        completed_tasks = [
            task for task in st.session_state.data["todo"] 
            if task.get("completed") and task.get("completed_at")
        ]
        if not completed_tasks:
            st.info("No tasks completed yet. Remember to set some time aside to work on your goals!")
        else:
            grouped_tasks = {}
            for task in completed_tasks:
                try:
                    date_obj = datetime.datetime.fromisoformat(task["completed_at"]).date()
                    date_str = date_obj.strftime("%Y-%m-%d")
                except Exception:
                    continue
                grouped_tasks.setdefault(date_str, []).append(task["task"])

            for date_str in sorted(grouped_tasks.keys(), reverse=True):
                st.markdown(f"### **{date_str}**")
                for i, task_desc in enumerate(grouped_tasks[date_str], start=1):
                    st.markdown(f"- {task_desc}")
                st.markdown("---")
