import streamlit as st
import bcrypt
import json
import firebase_admin
from firebase_admin import credentials, db

# ---------------------------
# Page Config: Hide Sidebar
# ---------------------------
st.set_page_config(page_title="Login/Register", initial_sidebar_state="collapsed")

# ---------------------------
# Initialize Firebase using st.secrets
# ---------------------------
firebase_creds = json.loads(st.secrets["FIREBASE"]["FIREBASE_CREDENTIALS"])
database_url = st.secrets["FIREBASE"]["FIREBASE_DATABASE_URL"]

if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred, {"databaseURL": database_url})

st.title("Welcome! Please Login or Create an Account")

# ---------------------------
# Helper Functions for Firebase User Management
# ---------------------------
def register_user(username, name, hashed_pw):
    """
    Register a new user by storing their credentials in Firebase under 'users/{username}/credentials'.
    Also initialize empty nodes for goals, habits, and streaks.
    Returns True if registration succeeded; False if the username already exists.
    """
    ref = db.reference("users/" + username)
    data = ref.get() or {}
    if "credentials" in data:
        return False  # User already exists.
    else:
        data["credentials"] = {"name": name, "password": hashed_pw}
        data["goals"] = {}
        data["habits"] = {}
        data["streaks"] = {}
        ref.set(data)
        return True

def login_user(username, password):
    """
    Check credentials stored in Firebase and return (True, name) if valid.
    """
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

# ---------------------------
# Login/Register UI
# ---------------------------
action = st.radio("Select Action", ["Login", "Register"])

if action == "Register":
    st.subheader("Create an Account")
    # Default to our desired user ("sammysams1234")
    username = st.text_input("Username", key="reg_username", value="sammysams1234")
    name = st.text_input("Name", key="reg_name", value="Samuel")
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
    username = st.text_input("Username", key="login_username", value="sammysams1234")
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
                st.success(f"Welcome, {name}!")
            else:
                st.error("Invalid username or password.")

# ---------------------------
# Automatic Redirect if Logged In (via JavaScript)
# ---------------------------
if "logged_in" in st.session_state and st.session_state.logged_in:
    st.write("<script>window.location.href='/habittracker';</script>", unsafe_allow_html=True)
    st.stop()
