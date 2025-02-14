import streamlit as st
import bcrypt
import json
import os
import firebase_admin
from firebase_admin import credentials, db

# --- Page config: Hide sidebar on login ---
st.set_page_config(page_title="Login/Register", initial_sidebar_state="collapsed")

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
        st.error("FIREBASE_CREDENTIALS and FIREBASE_DATABASE_URL must be set in the environment.")

st.title("Welcome! Please Login or Create an Account")

# --- Helper Functions for Firebase User Management ---
def register_user(username, name, hashed_pw):
    """Register a new user by storing their credentials in Firebase under 'users/{username}/credentials'."""
    ref = db.reference("users/" + username)
    data = ref.get() or {}
    if "credentials" in data:
        return False  # User already exists.
    else:
        data["credentials"] = {"name": name, "password": hashed_pw}
        ref.set(data)
        return True

def login_user(username, password):
    """Check credentials stored in Firebase and return (True, name) if valid."""
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

# --- UI: Let the user choose to Login or Register ---
action = st.radio("Select Action", ["Login", "Register"])

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
                st.success("Account created successfully! Logging you in...")
                st.session_state.logged_in = True
                st.session_state.username = username
                st.session_state.name = name
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
                st.success(f"Welcome, {name}!")
            else:
                st.error("Invalid username or password.")

# --- Automatic redirection to the habit tracker page if logged in ---
if "logged_in" in st.session_state and st.session_state.logged_in:
    # Use a meta refresh to redirect to the habit tracker page.
    st.markdown("<meta http-equiv='refresh' content='0; url=/habittracker'>", unsafe_allow_html=True)
    st.stop()
