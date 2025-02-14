import streamlit as st
import datetime
import os
import calendar
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from wordcloud import WordCloud
import json
import hashlib
import base64

# ----------------------------------
# Helper function to get Base64 image
# ----------------------------------
def get_base64_image(image_path):
    with open(image_path, "rb") as img_file:
        encoded = base64.b64encode(img_file.read()).decode()
    return encoded

# -------------------------------
# Firebase Admin Imports & Setup
# -------------------------------
import firebase_admin
from firebase_admin import credentials, db

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

# ----------------------------------------------------
# PAGE CONFIGURATION & CUSTOM CSS
# ----------------------------------------------------
st.set_page_config(
    page_title="Pulse",
    page_icon="assets/app_icon.png",
    layout="centered"
)

st.markdown(
    """
    <style>
    .reportview-container .main .block-container { padding-top: 1rem; }
    .calendar-container { overflow-x: auto; padding-bottom: 1rem; }
    .habit-column { min-width: 180px; text-align: left; font-weight: bold; padding-right: 10px; white-space: nowrap; }
    .calendar-container button {
         width: 50px !important; height: 50px !important; font-size: 24px !important;
         padding: 0 !important; margin: 0 !important; line-height: 50px !important;
         text-align: center !important; display: flex !important;
         justify-content: center !important; align-items: center !important;
         border-radius: 8px !important; border: 2px solid rgba(255, 255, 255, 0.2) !important;
         background-color: transparent !important;
    }
    .calendar-container button span {
         display: flex !important; justify-content: center !important; align-items: center !important;
         width: 100% !important; height: 100% !important;
    }
    </style>
    """, unsafe_allow_html=True,
)

# ----------------------------------------------------
# CONFIGURATION & DATA PERSISTENCE (User-Specific Data)
# ----------------------------------------------------
OUTCOME_COLORS = {
    "succeeded": "#4BB543",
    "failed": "transparent"
}

def load_user_data(user_id):
    ref = db.reference(f"users/{user_id}")
    data = ref.get()
    if not isinstance(data, dict):
        data = {}
    if "habits" not in data or not isinstance(data["habits"], dict):
        data["habits"] = {}
        ref.child("habits").set(data["habits"])
    if "goals" not in data or not isinstance(data["goals"], dict):
        data["goals"] = {}
        ref.child("goals").set(data["goals"])
    # Initialize streaks if not present:
    if "streaks" not in data or not isinstance(data["streaks"], dict):
        data["streaks"] = {}
        ref.child("streaks").set(data["streaks"])
    # (Optional) Migrate habit name if needed:
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

# ----------------------------------------------------
# UTILITY FUNCTIONS
# ----------------------------------------------------
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
        if habit_data.get(d_str) == "succeeded":
            streak += 1
            d -= datetime.timedelta(days=1)
        else:
            break
    return streak

def compute_longest_streak(habit_data, today):
    dates = [datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
             for d_str in habit_data
             if datetime.datetime.strptime(d_str, "%Y-%m-%d").date() <= today]
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
    color = '#' + h[:6]
    return color

# Helper function to update streaks for a habit
def update_streaks_for_habit(user_id, habit, habit_data, today):
    current_streak = compute_current_streak(habit_data, today)
    longest_streak = compute_longest_streak(habit_data, today)
    today_str = today.strftime("%Y-%m-%d")
    data_to_store = {
        "current": current_streak,
        "longest": longest_streak,
        "last_update": today_str
    }
    if "streaks" not in st.session_state.data:
        st.session_state.data["streaks"] = {}
    st.session_state.data["streaks"][habit] = data_to_store
    # Save to Firebase:
    ref = db.reference(f"users/{user_id}/streaks/{habit}")
    ref.set(data_to_store)

# ------------------------------------------
# Custom rerun function
# ------------------------------------------
def force_rerun():
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()

# ----------------------------------------------------
# INITIALIZE SESSION STATE
# ----------------------------------------------------
user_id = "default_user"
if "data" not in st.session_state:
    st.session_state.data = load_user_data(user_id)
if "tracker_month" not in st.session_state:
    st.session_state.tracker_month = datetime.date.today().replace(day=1)
if "analytics_view" not in st.session_state:
    st.session_state.analytics_view = "Compare to Last Week"

# ----------------------------------------------------
# Update streaks for each habit on every load
# ----------------------------------------------------
today = datetime.date.today()
today_str = today.strftime("%Y-%m-%d")
for habit in st.session_state.data["habits"]:
    update_streaks_for_habit(user_id, habit, st.session_state.data["habits"][habit], today)

# ----------------------------------------------------
# PAGE HEADER: Robot Logo & Animated Speech Bubble
# ----------------------------------------------------
# Embed the robot logo image as Base64
base64_image = get_base64_image("assets/app_icon.png")
st.markdown(
    f"""
    <div style="display: flex; align-items: center; margin-bottom: 20px;">
        <img src="data:image/png;base64,{base64_image}" alt="Robot Logo" style="height: 100px; margin-right: 20px;">
        <div style="position: relative; background: #f0f0f0; border-radius: 10px; padding: 10px 20px; max-width: 300px;">
            <p id="typed" style="font-size: 24px; margin: 0;"></p>
            <div style="position: absolute; bottom: -10px; left: 20px; width: 0; height: 0; border-top: 10px solid #f0f0f0; border-left: 10px solid transparent; border-right: 10px solid transparent;"></div>
        </div>
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
    """,
    unsafe_allow_html=True
)

###########################################
# Manage Habits Section (Add, Edit Goal & Remove)
###########################################
with st.expander("Manage Habits", expanded=False):
    st.subheader("Add Habit")
    new_habit = st.text_input("Habit Name", key="new_habit_input")
    new_goal = st.number_input("Set Goal (number of successes per week)", min_value=1, value=1, key="new_goal_input")
    if st.button("Add Habit"):
        new_habit = new_habit.strip()
        if not new_habit:
            st.error("Please enter a valid habit name.")
        elif new_habit in st.session_state.data["habits"]:
            st.error("This habit already exists!")
        else:
            st.session_state.data["habits"][new_habit] = {}
            st.session_state.data["goals"][new_habit] = int(new_goal)
            # Initialize streaks for new habit
            update_streaks_for_habit(user_id, new_habit, st.session_state.data["habits"][new_habit], today)
            save_user_data(user_id, st.session_state.data)
            st.success(f"Habit '{new_habit}' added successfully!")
            force_rerun()

    st.subheader("Manage Existing Habits")
    if st.session_state.data["habits"]:
        # For each habit, display the habit name, its current goal (editable),
        # an "Update" button to save a new goal, and a "Remove" button.
        for habit in list(st.session_state.data["habits"].keys()):
            current_goal = st.session_state.data["goals"].get(habit, 1)
            col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
            col1.markdown(f"**{habit}**")
            # Editable numeric input for goal
            new_goal_val = col2.number_input("Goal", min_value=1, value=current_goal, key=f"edit_goal_{habit}")
            if col3.button("Update", key=f"update_goal_{habit}"):
                st.session_state.data["goals"][habit] = new_goal_val
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

#############################
# Habit Tracker Section (Weekly Editing)
#############################
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
            # Update streaks immediately after a habit update
            update_streaks_for_habit(user_id, habit, st.session_state.data["habits"][habit], today)
    
    # When displaying streaks, pull from stored streak data:
    streak_data = st.session_state.data.get("streaks", {}).get(habit, {})
    current_streak = streak_data.get("current", 0)
    longest_streak = streak_data.get("longest", 0)
    row_cols[8].markdown(f"**{current_streak}**")
    row_cols[9].markdown(f"**{longest_streak}**")
st.markdown('</div>', unsafe_allow_html=True)

#############################
# Analytics Section
#############################
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
        ["Compare to Last Week", "Monthly", "Yearly"],
        index=["Compare to Last Week", "Monthly", "Yearly"].index(st.session_state.analytics_view)
    )
    st.session_state.analytics_view = view_option
    df = pd.DataFrame(records)
    
    if view_option == "Compare to Last Week":
        current_week_start = today - datetime.timedelta(days=today.weekday())
        current_week_end = current_week_start + datetime.timedelta(days=6)
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
        summary_compare["goal"] = summary_compare["habit"].apply(lambda habit: st.session_state.data["goals"].get(habit, 0))
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
            value_str = f"{row['current_success_count']} / {goal_val} ({current_pct:.0f}%)"
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
                
    elif view_option == "Monthly":
        df["month"] = df["date"].dt.to_period("M").astype(str)
        monthly = df.groupby(["month", "habit"]).size().reset_index(name="success_count")
        monthly = monthly.sort_values("month")
        fig_monthly = px.line(
            monthly,
            x="month",
            y="success_count",
            color="habit",
            markers=True,
            color_discrete_map=habit_colors,
            template="plotly_white"
        )
        st.plotly_chart(fig_monthly, use_container_width=True)
        col_prev, col_center, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("◀ Previous Month"):
                st.session_state.tracker_month = shift_month(st.session_state.tracker_month, -1)
        with col_next:
            if st.button("Next Month ▶"):
                st.session_state.tracker_month = shift_month(st.session_state.tracker_month, 1)
        year = st.session_state.tracker_month.year
        month = st.session_state.tracker_month.month
        num_days = calendar.monthrange(year, month)[1]
        days = [datetime.date(year, month, d) for d in range(1, num_days + 1)]
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
        colorscale = [
            [0.0, "#eaeaea"],
            [0.333, "#eaeaea"],
            [0.333, "rgba(0,0,0,0)"],
            [0.667, "rgba(0,0,0,0)"],
            [0.667, "#4BB543"],
            [1.0, "#4BB543"]
        ]
        fig_heatmap = go.Figure(data=go.Heatmap(
            z=heatmap_data,
            x=[str(day.day) for day in days],
            y=list(st.session_state.data["habits"].keys()),
            text=text_data,
            hoverinfo="text",
            colorscale=colorscale,
            zmin=0,
            zmax=2,
            showscale=False,
            xgap=0,
            ygap=0
        ))
        fig_heatmap.update_layout(
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=False),
            template="plotly_white"
        )
        st.plotly_chart(fig_heatmap, use_container_width=True)
        
    elif view_option == "Yearly":
        df["year"] = df["date"].dt.year
        yearly = df.groupby(["year", "habit"]).size().reset_index(name="success_count")
        yearly = yearly.sort_values("year")
        fig_yearly = px.line(
            yearly,
            x="year",
            y="success_count",
            color="habit",
            markers=True,
            color_discrete_map=habit_colors,
            template="plotly_white",
            title="Yearly Success Trends"
        )
        st.plotly_chart(fig_yearly, use_container_width=True)
        
        if "tracker_year" not in st.session_state:
            st.session_state.tracker_year = today.year

        col_prev, col_center, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("◀ Previous Year"):
                st.session_state.tracker_year -= 1
                force_rerun()
        with col_center:
            st.markdown(f"### {st.session_state.tracker_year}")
        with col_next:
            if st.button("Next Year ▶"):
                st.session_state.tracker_year += 1
                force_rerun()

        selected_year = st.session_state.tracker_year
        df_year = df[df["date"].dt.year == selected_year].copy()
        df_year["month"] = df_year["date"].dt.month
        yearly_pivot = df_year.groupby(["habit", "month"]).size().reset_index(name="count")
        if not yearly_pivot.empty:
            yearly_pivot = yearly_pivot.pivot(index="habit", columns="month", values="count").fillna(0)
        else:
            habits_list = list(st.session_state.data["habits"].keys())
            yearly_pivot = pd.DataFrame(0, index=habits_list, columns=range(1, 13))

        months = list(range(1, 13))
        for m in months:
            if m not in yearly_pivot.columns:
                yearly_pivot[m] = 0
        yearly_pivot = yearly_pivot[months]
        month_names = [calendar.month_abbr[m] for m in months]
        heatmap_matrix = yearly_pivot.values

        text_data = []
        for habit in yearly_pivot.index:
            row_text = []
            for m in months:
                count = yearly_pivot.loc[habit, m]
                row_text.append(f"{habit} in {calendar.month_abbr[m]} {selected_year}: {int(count)} successes")
            text_data.append(row_text)

        if heatmap_matrix.max() == 0:
            colorscale_used = [[0, "#eaeaea"], [1, "#eaeaea"]]
        else:
            colorscale_used = [
                [0.0, "#eaeaea"],
                [0.5, "#A8D08D"],
                [1.0, "#4BB543"]
            ]
        
        fig_year_heatmap = go.Figure(data=go.Heatmap(
            z=heatmap_matrix,
            x=month_names,
            y=yearly_pivot.index,
            text=text_data,
            hoverinfo="text",
            colorscale=colorscale_used,
            showscale=True
        ))
        fig_year_heatmap.update_layout(
            title=f"Monthly Success Heatmap for {selected_year}",
            template="plotly_white"
        )
        st.plotly_chart(fig_year_heatmap, use_container_width=True)
