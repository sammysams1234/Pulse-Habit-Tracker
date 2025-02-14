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
from firebase_admin import credentials, db
import streamlit.components.v1 as components

# --- Require Login ---
if "logged_in" not in st.session_state or not st.session_state.logged_in:
    st.error("You must be logged in to view this page. Please go to the login page.")
    st.stop()

# Use the logged-in username as the unique user ID.
user_id = st.session_state.username  # For example: "sammysams1234"

# --- Page Config ---
st.set_page_config(page_title="Pulse", page_icon="assets/app_icon.png", layout="centered")

# --- Initialize Firebase (if not already initialized) ---
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
        st.error("FIREBASE_CREDENTIALS and FIREBASE_DATABASE_URL must be set.")

# --- Helper Function: Get Base64 Image ---
def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            encoded = base64.b64encode(img_file.read()).decode()
        return encoded
    except Exception as e:
        st.error(f"Error loading image at {image_path}: {e}")
        return ""

# --- Configuration & Data Persistence ---
OUTCOME_COLORS = {"succeeded": "#4BB543", "failed": "transparent"}
success_green = "#4BB543"

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
    # Optional: Migrate habit names if needed.
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

# --- Modified compute_current_streak Function ---
def compute_current_streak(habit_data, today):
    streak = 0
    d = today

    while True:
        d_str = d.strftime("%Y-%m-%d")

        if d == today:
            # Today logic:
            if d_str in habit_data:
                if habit_data[d_str] == "succeeded":
                    # If explicitly succeeded today, increment
                    streak += 1
                else:
                    # If "failed" or anything else, break
                    break
            else:
                # If unmarked today, do not break or increment
                pass
        else:
            # Past days must be explicitly "succeeded" to continue
            if d_str not in habit_data or habit_data[d_str] != "succeeded":
                break
            else:
                # Succeeded => increment streak
                streak += 1

        # Move to the previous day
        d -= datetime.timedelta(days=1)
        
        # Optional safety stop if you like:
        # if d < some_min_date:
        #     break

    return streak

    # Now count backwards for previous days
    d = today - datetime.timedelta(days=1)
    while True:
        d_str = d.strftime("%Y-%m-%d")
        if habit_data.get(d_str) == "succeeded":
            streak += 1
            d -= datetime.timedelta(days=1)
        else:
            break
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

def force_rerun():
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()

# --- Initialize Session State ---
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

# --- Page Header: Logo & Animated Messages ---
base64_image = get_base64_image("assets/app_icon.png")
header_html = f"""
<div style="display: flex; align-items: center; margin-bottom: 20px;">
    <img src="data:image/png;base64,{base64_image}" alt="App Icon" style="height: 100px; margin-right: 20px;">
    <p id="typed" style="font-size: 24px; margin: 0; color: white;"></p>
</div>
<script src="https://cdn.jsdelivr.net/npm/typed.js@2.0.12"></script>
<script>
  var typed = new Typed('#typed', {{
    strings: ["Remember why you started", "Remember the euphoric highs of success", "Follow yourself"],
    typeSpeed: 50,
    backSpeed: 25,
    backDelay: 2000,
    loop: true
  }});
</script>
"""
components.html(header_html, height=150)

# --- Manage Habits Section ---
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
            force_rerun()

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
                force_rerun()
            if col4.button("Remove", key=f"remove_{habit}"):
                st.session_state.data["habits"].pop(habit, None)
                st.session_state.data["goals"].pop(habit, None)
                if "streaks" in st.session_state.data and habit in st.session_state.data["streaks"]:
                    st.session_state.data["streaks"].pop(habit, None)
                save_user_data(user_id, st.session_state.data)
                st.success(f"Habit '{habit}' removed successfully!")
                force_rerun()
    else:
        st.info("No habits available.")

# --- Habit Tracker Section (Weekly Editing) ---
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
        if outcome == "succeeded":
            label = "✅"
        elif outcome == "failed":
            label = "❌"
        else:
            label = str(current_date.day)
        if row_cols[i+1].button(label, key=f"weekly_{habit}_{date_str}"):
            current_outcome = st.session_state.data["habits"][habit].get(date_str, None)
            if current_outcome is None:
                new = "succeeded"
            elif current_outcome == "succeeded":
                new = "failed"
            elif current_outcome == "failed":
                new = None
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

# --- Analytics Section ---
st.markdown("---")
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
    st.info("No habit success data available yet. Start tracking your habits!")
else:
    view_option = st.selectbox(
        "Select Analytics View",
        ["Weekly", "Monthly", "Yearly"],
        index=["Weekly", "Monthly", "Yearly"].index(st.session_state.analytics_view)
    )
    st.session_state.analytics_view = view_option
    df = pd.DataFrame(records)
    
    if view_option == "Weekly":
        current_week_start = st.session_state.tracker_week
        current_week_end = current_week_start + datetime.timedelta(days=6)
        col_prev, col_center, col_next = st.columns([1,2,1])
        with col_prev:
            if st.button("◀ Previous Week", key="prev_week"):
                st.session_state.tracker_week = st.session_state.tracker_week - datetime.timedelta(days=7)
                force_rerun()
        with col_center:
            st.markdown(f"### Week of {current_week_start.strftime('%Y-%m-%d')}")
        with col_next:
            if st.button("Next Week ▶", key="next_week"):
                st.session_state.tracker_week = st.session_state.tracker_week + datetime.timedelta(days=7)
                force_rerun()
        
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
                current_summary = pd.concat([current_summary,
                                             pd.DataFrame([{"habit": habit, "current_success_count": 0}])],
                                            ignore_index=True)
            if habit not in last_summary["habit"].values:
                last_summary = pd.concat([last_summary,
                                          pd.DataFrame([{"habit": habit, "last_success_count": 0}])],
                                         ignore_index=True)
        summary_compare = pd.merge(current_summary, last_summary, on="habit", how="outer").fillna(0)
        summary_compare["current_success_count"] = summary_compare["current_success_count"].astype(int)
        summary_compare["last_success_count"] = summary_compare["last_success_count"].astype(int)
        summary_compare["goal"] = summary_compare["habit"].apply(lambda habit: int(st.session_state.data["goals"].get(habit, 0)))
        cols = st.columns(3)
        sorted_compare = summary_compare.sort_values("habit").reset_index(drop=True)
        for idx, row in sorted_compare.iterrows():
            habit = row["habit"]
            goal_val = row["goal"]
            if row["last_success_count"] > 0:
                delta_value = row["current_success_count"] - row["last_success_count"]
                delta_str = f"{delta_value:+}"
            else:
                delta_str = "N/A"
            if goal_val > 0:
                current_pct = row["current_success_count"] / goal_val * 100
            else:
                current_pct = 0
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
        colorscale_weekly = [
            [0.0, "#eaeaea"],
            [0.5, "rgba(0,0,0,0)"],
            [1.0, success_green]
        ]
        fig_heatmap_weekly = go.Figure(data=go.Heatmap(
            z=heatmap_data_weekly,
            x=[day.strftime("%a") for day in week_dates],
            y=list(st.session_state.data["habits"].keys()),
            text=text_data_weekly,
            hoverinfo="text",
            colorscale=colorscale_weekly,
            zmin=0,
            zmax=2,
            showscale=False,
            xgap=3,
            ygap=3
        ))
        fig_heatmap_weekly.update_layout(
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=False),
            template="plotly_white",
        )
        st.plotly_chart(fig_heatmap_weekly, use_container_width=True)
                
    elif view_option == "Monthly":
        current_month_start = st.session_state.tracker_month
        year = current_month_start.year
        month = current_month_start.month
        num_days = calendar.monthrange(year, month)[1]
        current_month_end = datetime.date(year, month, num_days)
        col_prev, col_center, col_next = st.columns([1,2,1])
        with col_prev:
            if st.button("◀ Previous Month", key="prev_month"):
                st.session_state.tracker_month = shift_month(current_month_start, -1)
                force_rerun()
        with col_center:
            st.markdown(f"### {current_month_start.strftime('%B %Y')}")
        with col_next:
            if st.button("Next Month ▶", key="next_month"):
                st.session_state.tracker_month = shift_month(current_month_start, 1)
                force_rerun()
        
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
        summary_compare["goal"] = summary_compare["habit"].apply(
            lambda habit: int(st.session_state.data["goals"].get(habit, 0) / 7 * num_days)
        )
        cols = st.columns(3)
        sorted_compare = summary_compare.sort_values("habit").reset_index(drop=True)
        for idx, row in sorted_compare.iterrows():
            habit = row["habit"]
            goal_val = row["goal"]
            if row["prev_success_count"] > 0:
                delta_value = row["current_success_count"] - row["prev_success_count"]
                delta_str = f"{delta_value:+}"
            else:
                delta_str = "N/A"
            if goal_val > 0:
                current_pct = row["current_success_count"] / goal_val * 100
            else:
                current_pct = 0
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
        colorscale_monthly = [
            [0.0, "#eaeaea"],
            [0.5, "rgba(0,0,0,0)"],
            [1.0, success_green]
        ]
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=heatmap_data,
            x=[str(day.day) for day in days],
            y=list(st.session_state.data["habits"].keys()),
            text=text_data,
            hoverinfo="text",
            colorscale=colorscale_monthly,
            zmin=0,
            zmax=2,
            showscale=False,
            xgap=3,
            ygap=3
        ))
        fig_heatmap.update_layout(
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=False),
            template="plotly_white",
        )
        st.plotly_chart(fig_heatmap, use_container_width=True)
                
    elif view_option == "Yearly":
        if "tracker_year" not in st.session_state:
            st.session_state.tracker_year = today.year
        selected_year = st.session_state.tracker_year
        col_prev, col_center, col_next = st.columns([1,2,1])
        with col_prev:
            if st.button("◀ Previous Year", key="prev_year"):
                st.session_state.tracker_year = st.session_state.tracker_year - 1
                force_rerun()
        with col_center:
            st.markdown(f"### {selected_year}")
        with col_next:
            if st.button("Next Year ▶", key="next_year"):
                st.session_state.tracker_year = st.session_state.tracker_year + 1
                force_rerun()
        
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
        summary_compare["goal"] = summary_compare["habit"].apply(
            lambda habit: int(st.session_state.data["goals"].get(habit, 0) / 7 * days_in_year)
        )
        cols = st.columns(3)
        sorted_compare = summary_compare.sort_values("habit").reset_index(drop=True)
        for idx, row in sorted_compare.iterrows():
            habit = row["habit"]
            goal_val = row["goal"]
            if row["prev_success_count"] > 0:
                delta_value = row["current_success_count"] - row["prev_success_count"]
                delta_str = f"{delta_value:+}"
            else:
                delta_str = "N/A"
            if goal_val > 0:
                current_pct = row["current_success_count"] / goal_val * 100
            else:
                current_pct = 0
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
        colorscale_yearly = [
            [0.0, "#eaeaea"],
            [0.25, "#c7e9c0"],
            [0.5, "#a1d99b"],
            [0.75, "#74c476"],
            [1.0, success_green]
        ]
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=heatmap_data,
            x=month_names,
            y=list(st.session_state.data["habits"].keys()),
            text=text_data,
            hoverinfo="text",
            colorscale=colorscale_yearly,
            showscale=True,
            xgap=3,
            ygap=3
        ))
        fig_heatmap.update_layout(
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=False),
            template="plotly_white",
        )
        st.plotly_chart(fig_heatmap, use_container_width=True)
