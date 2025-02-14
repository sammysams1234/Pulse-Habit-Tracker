import streamlit as st
import bcrypt
import json
import os

# File to store user credentials
USERS_FILE = "users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    else:
        return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

st.title("Welcome! Please Login or Create an Account")

# Choose an action: Login or Register
action = st.radio("Select Action", ["Login", "Register"])

users = load_users()

if action == "Register":
    st.subheader("Create an Account")
    username = st.text_input("Username")
    name = st.text_input("Name")
    password = st.text_input("Password", type="password")
    confirm_password = st.text_input("Confirm Password", type="password")
    
    if st.button("Register"):
        if not username or not name or not password:
            st.error("Please fill in all fields.")
        elif password != confirm_password:
            st.error("Passwords do not match.")
        elif username in users:
            st.error("Username already exists. Please choose another.")
        else:
            hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            users[username] = {"name": name, "password": hashed_pw}
            save_users(users)
            st.success("Account created successfully! You can now log in.")

if action == "Login":
    st.subheader("Log In")
    username = st.text_input("Username", key="login_username")
    password = st.text_input("Password", type="password", key="login_password")
    
    if st.button("Login"):
        if username in users:
            stored_pw = users[username]["password"]
            if bcrypt.checkpw(password.encode(), stored_pw.encode()):
                st.session_state.logged_in = True
                st.session_state.username = username
                st.session_state.name = users[username]["name"]
                st.success(f"Welcome, {users[username]['name']}!")
            else:
                st.error("Invalid username or password.")
        else:
            st.error("Invalid username or password.")

if "logged_in" in st.session_state and st.session_state.logged_in:
    st.markdown("### You are logged in.")
    st.markdown("[Go to Habit Tracker](./habittracker)")
