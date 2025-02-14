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
    st.warning("OpenAI API key is not set in the environment. Journal summarization will not work.")

def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            encoded = base64.b64encode(img_file.read()).decode()
        return encoded
    except Exception as e:
        st.error(f"Error loading image at {image_path}: {e}")
        return ""

# =====================================================
# LOGIN & REGISTRATION (Always the FIRST screen)
# =====================================================
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    base64_image = get_base64_image("assets/app_icon.png")
    header_html = f"""
    <div style="display: flex; align-items: center; margin-bottom: 20px;">
        <img src="data:image/png;base64,{base64_image}" alt="App Icon" style="height: 100px; margin-right: 20px;">
        <h1 style="color: white; font-size: 32px;">Welcome to Pulse Habit Tracking! Please Login or Create an Account</h1>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)

    # --- Helper Functions for Firebase User Management ---
    def register_user(username, name, hashed_pw):
        ref = db.reference("users/" + username)
        data = ref.get() or {}
        if "credentials" in data:
            return False  # User already exists.
        else:
            data["credentials"] = {"name": name, "password": hashed_pw}
            data["goals"] = {}
            data["habits"] = {}
            data["streaks"] = {}
            data["journal"] = {}
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
                return True, creds.get("name")
            else:
                return False, None

    # --- UI: Choose to Login or Register ---
    action = st.radio("", ["Login", "Register"])

    if action == "Register":
        st.subheader("Create an Account")
        username = st.text_input("Username", key="reg_username")
        name = st.text_input("Name", key="reg_name")
        password = st.text_input("Password", type="password", key="reg_password")
        confirm_password = st.text_input("Confirm Password", type="password", key="reg_confirm")
        
        if st.button("Register"):
            if not username or not name or not password:
                st.error("Please fill in all fields.")
            elif password != confirm_password:
                st.error("Passwords do not match.")
            else:
                hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                success = register_user(username, name, hashed_pw)
                if success:
                    st.success("Account created successfully! Please switch to the Login tab and log in.")
                else:
                    st.error("Username already exists. Please choose another.")

    if action == "Login":
        st.subheader("Log In")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        
        if st.button("Login"):
            if not username or not password:
                st.error("Please enter both username and password.")
            else:
                success, name = login_user(username, password)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.session_state.name = name
                    # Set default page to Habit Tracker so it mimics a sidebar click.
                    st.session_state.page = "Habit Tracker 📆"
                    st.success(f"Welcome, {name}!")
                else:
                    st.error("Invalid username or password.")
    st.stop()  # Stop execution until the user logs in.

# =====================================================
# HELPER FUNCTIONS COMMON TO HABIT TRACKER & JOURNAL
# =====================================================

def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            encoded = base64.b64encode(img_file.read()).decode()
        return encoded
    except Exception as e:
        st.error(f"Error loading image at {image_path}: {e}")
        return ""

# =====================================================
# HABIT TRACKER FUNCTIONS & INITIALIZATION
# =====================================================

user_id = st.session_state.username

def load_user_data(user_id):
    ref = db.reference(f"users/{user_id}")
    data = ref.get() or {}
    if "habits" not in data or not isinstance(data["habits"], dict):
        data["habits"] = {}
        ref.child("habits").set(data["habits"])
    if "goals" not in data or not isinstance(data["goals"], dict):
        data["goals"] = {}
        ref.child("goals").set(data["goals"])
    if "streaks" not in data or not isinstance(data["streaks"], dict):
        data["streaks"] = {}
        ref.child("streaks").set(data["streaks"])
    if "journal" not in data or not isinstance(data["journal"], dict):
        data["journal"] = {}
        ref.child("journal").set(data["journal"])
    if "Sleeping before 12" in data["habits"]:
        data["habits"]["Sleep"] = data["habits"].pop("Sleeping before 12")
        ref.child("habits").set(data["habits"])
    return data

def save_user_data(user_id, data):
    ref = db.reference(f"users/{user_id}")
    ref.child("habits").set(data["habits"])
    ref.child("goals").set(data["goals"])
    if "streaks" in data:
        ref.child("streaks").set(data["streaks"])

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
    while True:
        d_str = d.strftime("%Y-%m-%d")
        if d == today:
            if d_str in habit_data:
                if habit_data[d_str] == "succeeded":
                    streak += 1
                else:
                    break
        else:
            if d_str not in habit_data or habit_data[d_str] != "succeeded":
                break
            else:
                streak += 1
        d -= datetime.timedelta(days=1)
    return streak

def compute_longest_streak(habit_data, today):
    dates = [datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
             for d_str in habit_data if datetime.datetime.strptime(d_str, "%Y-%m-%d").date() <= today]
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
    ref = db.reference(f"users/{user_id}/streaks/{habit}")
    ref.set(data_to_store)

if "data" not in st.session_state:
    st.session_state.data = load_user_data(user_id)
if "tracker_month" not in st.session_state:
    st.session_state.tracker_month = datetime.date.today().replace(day=1)
if "analytics_view" not in st.session_state:
    st.session_state.analytics_view = "Weekly"
if "tracker_week" not in st.session_state:
    today = datetime.date.today()
    st.session_state.tracker_week = today - datetime.timedelta(days=today.weekday())

today = datetime.date.today()
today_str = today.strftime("%Y-%m-%d")
for habit in st.session_state.data["habits"]:
    update_streaks_for_habit(user_id, habit, st.session_state.data["habits"][habit], today)

# =====================================================
# JOURNAL FUNCTIONS
# =====================================================

def get_journal_entry(user_id, date_str):
    ref = db.reference(f"users/{user_id}/journal/{date_str}")
    return ref.get()

def save_journal_entry(user_id, date_str, entry):
    ref = db.reference(f"users/{user_id}/journal/{date_str}")
    ref.set(entry)

def fetch_journal_entries(user_id):
    ref = db.reference(f"users/{user_id}/journal")
    entries = ref.get()
    if not isinstance(entries, dict):
        entries = {}
    return entries

def filter_entries_by_period(entries, period, today):
    filtered = {}
    for date_str, entry in entries.items():
        try:
            entry_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            continue
        if period == "Daily" and entry_date == today:
            filtered[date_str] = entry
        elif period == "Weekly":
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
        "Provide a brief motivational summary that helps me stay positive and focused.\n\n"
        f"{entries_text}"
    )
    try:
        response = openai.ChatCompletion.create(
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

# =====================================================
# APP NAVIGATION (Sidebar)
# =====================================================

if "page" not in st.session_state:
    st.session_state.page = "Habit Tracker 📆"

page_options = ["Habit Tracker 📆", "Journal 🗒️"]
page = st.sidebar.radio("Navigation", page_options, index=page_options.index(st.session_state.page))
st.session_state.page = page
st.sidebar.write(f"Logged in as **{st.session_state.name}**")

# -------------------------------
# HEADER: LOGO & MOTIVATIONAL MESSAGES
# -------------------------------
base64_image = get_base64_image("assets/app_icon.png")
header_html = f"""
<div style="display: flex; align-items: center; margin-bottom: 20px;">
    <img src="data:image/png;base64,{base64_image}" alt="App Icon" style="height: 100px; margin-right: 20px;">
    <p id="typed" style="font-size: 24px; margin: 0; color: white;"></p>
</div>
<script src="https://cdn.jsdelivr.net/npm/typed.js@2.0.12"></script>
<script>
  var typed = new Typed('#typed', {{
    strings: ["Remember why you started", "Embrace the journey", "Stay positive, {st.session_state.name}!"],
    typeSpeed: 50,
    backSpeed: 25,
    backDelay: 2000,
    loop: true
  }});
</script>
"""
components.html(header_html, height=150)

# =====================================================
# PAGE: HABIT TRACKER & ANALYTICS
# =====================================================
if page == "Habit Tracker 📆":
    st.markdown("### Weekly Habit Tracker")
    
    # -------------------------------
    # Manage Habits Section
    # -------------------------------
    # Expand the habit manager if no habits exist.
    with st.expander("Manage Habits", expanded=False):
        st.subheader("Add Habit")
        new_habit = st.text_input("Habit", key="new_habit_input")
        new_goal = st.number_input("Set Goal", min_value=1, value=1, key="new_goal_input")
        if st.button("Add Habit"):
            new_habit = new_habit.strip()
            if not new_habit:
                st.error("Please enter a valid habit.")
            elif new_habit in st.session_state.data["habits"]:
                st.error("This habit already exists!")
            else:
                st.session_state.data["habits"][new_habit] = {}
                st.session_state.data["goals"][new_habit] = int(new_goal)
                update_streaks_for_habit(user_id, new_habit, st.session_state.data["habits"][new_habit], today)
                save_user_data(user_id, st.session_state.data)
                st.success(f"Habit '{new_habit}' added successfully!")
        
        st.subheader("Manage Habits")
        if st.session_state.data["habits"]:
            for habit in list(st.session_state.data["habits"].keys()):
                current_goal = int(st.session_state.data["goals"].get(habit, 0))
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
                col1.markdown(f"**{habit}**")
                new_goal_val = st.number_input("Goal", min_value=1, value=current_goal, key=f"edit_goal_{habit}")
                if col3.button("Update", key=f"update_goal_{habit}"):
                    st.session_state.data["goals"][habit] = int(new_goal_val)
                    save_user_data(user_id, st.session_state.data)
                    st.success(f"Updated goal for '{habit}' to {new_goal_val}!")
                if col4.button("Remove", key=f"remove_{habit}"):
                    st.session_state.data["habits"].pop(habit, None)
                    st.session_state.data["goals"].pop(habit, None)
                    if "streaks" in st.session_state.data and habit in st.session_state.data["streaks"]:
                        st.session_state.data["streaks"].pop(habit, None)
                    save_user_data(user_id, st.session_state.data)
                    st.success(f"Habit '{habit}' removed successfully!")
        else:
            st.info("No habits available yet.")

    # If there are no habits, hide the rest of the tracker/analytics views.
    if not st.session_state.data["habits"]:
        st.info("No habit data available yet. Start tracking your habits by adding one above!")
        st.stop()

    # -------------------------------
    # Habit Tracker Section (Weekly Editing)
    # -------------------------------
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
                new = "succeeded" if current_outcome is None else "failed" if current_outcome == "succeeded" else None
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

    # -------------------------------
    # Analytics Section
    # -------------------------------
    st.markdown("---")
    # Container for the analytics filter dropdown:
    with st.container():
        st.markdown("### Analytics")
        view_option = st.selectbox(
            "Filter analytics view:",
            ["Weekly", "Monthly", "Yearly"],
            index=["Weekly", "Monthly", "Yearly"].index(st.session_state.analytics_view)
        )
        st.session_state.analytics_view = view_option

    habit_colors = {habit: get_habit_color(habit) for habit in st.session_state.data["habits"].keys()}
    records = []
    for habit, days in st.session_state.data["habits"].items():
        for date_str, outcome in days.items():
            if outcome == "succeeded":
                try:
                    date_obj = pd.to_datetime(date_str)
                    records.append({"habit": habit, "date": date_obj})
                except Exception:
                    pass
    if not records:
        st.info("No habit tracking data available yet. Start tracking your habits by marking the calendar!")
    else:
        df = pd.DataFrame(records)
        if view_option == "Weekly":
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
            mask_current = (df["date"].dt.date >= current_week_start) & (df["date"].dt.date <= current_week_end)
            mask_last = (df["date"].dt.date >= last_week_start) & (df["date"].dt.date <= last_week_end)
            df_current = df[mask_current]
            df_last = df[mask_last]
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
            summary_compare["goal"] = summary_compare["habit"].apply(lambda habit: int(st.session_state.data["goals"].get(habit, 0)))
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
            st.plotly_chart(fig_compare, use_container_width=True)
                    
            week_dates = [current_week_start + datetime.timedelta(days=i) for i in range(7)]
            heatmap_data_weekly = []
            text_data_weekly = []
            for habit in st.session_state.data["habits"].keys():
                row = []
                text_row = []
                for day in week_dates:
                    day_str = day.strftime("%Y-%m-%d")
                    outcome = st.session_state.data["habits"][habit].get(day_str)
                    if outcome == "succeeded":
                        val = 2
                        text = f"{day_str}: Succeeded"
                    elif outcome == "failed":
                        val = 1
                        text = f"{day_str}: Failed"
                    else:
                        val = 0
                        text = f"{day_str}: No Data"
                    row.append(val)
                    text_row.append(text)
                heatmap_data_weekly.append(row)
                text_data_weekly.append(text_row)
            fig_heatmap_weekly = go.Figure(data=go.Heatmap(
                z=heatmap_data_weekly,
                x=[day.strftime("%a") for day in week_dates],
                y=list(st.session_state.data["habits"].keys()),
                text=text_data_weekly,
                hoverinfo="text",
                colorscale=[[0.0, "#eaeaea"], [0.5, "rgba(0,0,0,0)"], [1.0, "#4BB543"]],
                zmin=0,
                zmax=2,
                showscale=False,
                xgap=3,
                ygap=3
            ))
            fig_heatmap_weekly.update_layout(xaxis=dict(showgrid=False), yaxis=dict(showgrid=False), template="plotly_white")
            st.plotly_chart(fig_heatmap_weekly, use_container_width=True)
        
        elif view_option == "Monthly":
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
            mask_current = (df["date"].dt.date >= current_month_start) & (df["date"].dt.date <= current_month_end)
            mask_prev = (df["date"].dt.date >= prev_month_start) & (df["date"].dt.date <= prev_month_end)
            df_current = df[mask_current]
            df_prev = df[mask_prev]
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
            summary_compare["goal"] = summary_compare["habit"].apply(lambda habit: int(st.session_state.data["goals"].get(habit, 0) / 7 * num_days))
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
            st.plotly_chart(fig_compare, use_container_width=True)
            days = [datetime.date(year, month, d) for d in range(1, num_days+1)]
            heatmap_data = []
            text_data = []
            for habit in st.session_state.data["habits"].keys():
                row = []
                text_row = []
                for day in days:
                    day_str = day.strftime("%Y-%m-%d")
                    outcome = st.session_state.data["habits"][habit].get(day_str)
                    if outcome == "succeeded":
                        val = 2
                        text = f"{day_str}: Succeeded"
                    elif outcome == "failed":
                        val = 1
                        text = f"{day_str}: Failed"
                    else:
                        val = 0
                        text = f"{day_str}: No Data"
                    row.append(val)
                    text_row.append(text)
                heatmap_data.append(row)
                text_data.append(text_row)
            fig_heatmap = go.Figure(data=go.Heatmap(
                z=heatmap_data,
                x=[str(day.day) for day in days],
                y=list(st.session_state.data["habits"].keys()),
                text=text_data,
                hoverinfo="text",
                colorscale=[[0.0, "#eaeaea"], [0.5, "rgba(0,0,0,0)"], [1.0, "#4BB543"]],
                zmin=0,
                zmax=2,
                showscale=False,
                xgap=3,
                ygap=3
            ))
            fig_heatmap.update_layout(xaxis=dict(showgrid=False), yaxis=dict(showgrid=False), template="plotly_white")
            st.plotly_chart(fig_heatmap, use_container_width=True)
        
        elif view_option == "Yearly":
            if "tracker_year" not in st.session_state:
                st.session_state.tracker_year = today.year
            selected_year = st.session_state.tracker_year
            col_prev, col_center, col_next = st.columns([1, 2, 1])
            with col_prev:
                if st.button("◀ Previous Year", key="prev_year"):
                    st.session_state.tracker_year -= 1
            with col_center:
                st.markdown(f"### {selected_year}")
            with col_next:
                if st.button("Next Year ▶", key="next_year"):
                    st.session_state.tracker_year += 1
            mask_current = (df["date"].dt.year == selected_year)
            mask_prev = (df["date"].dt.year == (selected_year - 1))
            df_current = df[mask_current]
            df_prev = df[mask_prev]
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
            days_in_year = 366 if calendar.isleap(selected_year) else 365
            summary_compare["goal"] = summary_compare["habit"].apply(lambda habit: int(st.session_state.data["goals"].get(habit, 0) / 7 * days_in_year))
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
            st.plotly_chart(fig_compare, use_container_width=True)
            
            months = list(range(1, 13))
            month_names = [calendar.month_abbr[m] for m in months]
            heatmap_data = []
            text_data = []
            for habit in st.session_state.data["habits"].keys():
                row = []
                text_row = []
                for m in months:
                    count = df_current[(df_current["habit"]==habit) & (df_current["date"].dt.month == m)].shape[0]
                    row.append(count)
                    text_row.append(f"{habit} in {calendar.month_abbr[m]} {selected_year}: {count} successes")
                heatmap_data.append(row)
                text_data.append(text_row)
            fig_heatmap = go.Figure(data=go.Heatmap(
                z=heatmap_data,
                x=month_names,
                y=list(st.session_state.data["habits"].keys()),
                text=text_data,
                hoverinfo="text",
                colorscale=[[0.0, "#eaeaea"], [0.25, "#c7e9c0"], [0.5, "#a1d99b"], [0.75, "#74c476"], [1.0, "#4BB543"]],
                showscale=True,
                xgap=3,
                ygap=3
            ))
            fig_heatmap.update_layout(xaxis=dict(showgrid=False), yaxis=dict(showgrid=False), template="plotly_white")
            st.plotly_chart(fig_heatmap, use_container_width=True)

# =====================================================
# PAGE: JOURNAL
# =====================================================
elif page == "Journal 🗒️":
    st.title("Daily Journal 📝")
    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")
    st.subheader(f"Journal Entry for {today_str}")
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
            if existing_entry and "summary" in existing_entry:
                entry["summary"] = existing_entry["summary"]
            save_journal_entry(user_id, today_str, entry)
            st.success(f"Journal entry for {today_str} saved successfully!")
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
                if summary_period == "Daily":
                    daily_entry = get_journal_entry(user_id, today_str) or {}
                    daily_entry["summary"] = summary
                    save_journal_entry(user_id, today_str, daily_entry)
                    st.info("Daily summary has been saved to your journal entry.")
    with st.expander("Show Past Journal Entries"):
        all_entries = fetch_journal_entries(user_id)
        if not all_entries:
            st.info("No journal entries recorded yet.")
        else:
            for date_str in sorted(all_entries.keys(), reverse=True):
                entry = all_entries[date_str]
                st.markdown(f"### {date_str}")
                st.markdown(f"**Feeling:** {entry.get('feeling', 'N/A')}")
                st.markdown(f"**Cause:** {entry.get('cause', 'N/A')}")
                summary_text = entry.get("summary")
                if summary_text:
                    st.markdown(f"{summary_text}")
                st.markdown("---")
