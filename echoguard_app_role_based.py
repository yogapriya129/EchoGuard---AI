from pathlib import Path
from datetime import date, datetime, time, timedelta
import pandas as pd
import streamlit as st
import re
import json
import hashlib
import hmac
import secrets
import sqlite3

st.set_page_config(page_title="EchoGuard AI", page_icon="🛡️", layout="wide")

DATA_FILE = Path(__file__).with_name("echoguard_requests.csv")  # CSV export/backup
DB_FILE = Path(__file__).with_name("echoguard.db")
EVIDENCE_DIR = Path(__file__).with_name("evidence_uploads")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
COLUMNS = [
    "Request ID", "Request Type", "Submission Date", "Expected Due Date",
    "Status", "Assigned To", "Last Updated", "Notes", "Student Name",
    "Activity Name", "Activity Date", "Activity Time", "Evidence File Name",
    "Evidence Verification", "Routing Group", "Faculty Notes", "College Response Date", "Department", "Student Username"
]
STATUSES = ["Submitted", "Under Review", "Waiting for Information", "In Progress", "Accepted", "Completed", "Rejected"]
TYPES = ["Internal OD", "External OD", "Bonafide Certificate", "Scholarship Application",
         "Exam Fee Correction", "ID Card Request", "Transcript Request", "Other"]
EVIDENCE_STATUSES = ["Evidence Required", "Pending Verification", "AI Review", "Verified", "Verification Issue", "Not Required"]
DEPARTMENTS = ["CSE", "ECE", "EEE", "AI & ML", "AI & DS", "Civil", "Mechanical", "IT", "Cybersecurity", "Other"]


def blank_data():
    return pd.DataFrame(columns=COLUMNS)


def db_connect():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS accounts (
            email TEXT PRIMARY KEY COLLATE NOCASE,
            role TEXT NOT NULL CHECK(role IN ('student','faculty')),
            name TEXT NOT NULL,
            department TEXT NOT NULL DEFAULT 'Other',
            profile_json TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)")
        conn.commit()


def password_record(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 240_000).hex()
    return salt, digest


def verify_password(password, salt, expected_hash):
    _, candidate = password_record(password, salt)
    return hmac.compare_digest(candidate, expected_hash)


def create_account(profile, password):
    email = profile['email'].strip().lower()
    salt, digest = password_record(password)
    with db_connect() as conn:
        try:
            conn.execute("INSERT INTO accounts(email,role,name,department,profile_json,password_salt,password_hash,created_at) VALUES(?,?,?,?,?,?,?,?)",
                         (email, profile['role'], profile['name'], profile.get('department','Other'),
                          json.dumps(profile), salt, digest, datetime.now().isoformat(timespec='seconds')))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def get_account(email):
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE email = ? COLLATE NOCASE", (email.strip().lower(),)).fetchone()
    if not row:
        return None
    profile = json.loads(row['profile_json'])
    profile.update({'email': row['email'], 'role': row['role'], 'name': row['name'], 'department': row['department']})
    return {'profile': profile, 'password_salt': row['password_salt'], 'password_hash': row['password_hash']}


def load_data():
    init_db()
    with db_connect() as conn:
        rows = conn.execute("SELECT payload_json FROM requests ORDER BY rowid").fetchall()
    if rows:
        records = [json.loads(row['payload_json']) for row in rows]
        df = pd.DataFrame(records)
    elif DATA_FILE.exists():
        # One-time import of existing CSV requests into SQLite.
        try:
            df = pd.read_csv(DATA_FILE, dtype={"Request ID": str})
        except Exception:
            st.error("Could not read echoguard_requests.csv. Check its columns and formatting.")
            df = blank_data()
    else:
        df = blank_data()
    for c in COLUMNS:
        if c not in df:
            df[c] = ""
    df = df[COLUMNS]
    date_columns = ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]
    for c in date_columns:
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    for c in COLUMNS:
        df[c] = df[c].fillna("")
    for c in COLUMNS:
        if c not in date_columns:
            df[c] = df[c].astype(str)
    for i, row in df.iterrows():
        if not row["Routing Group"]:
            df.at[i, "Routing Group"] = routing_group(row["Request Type"])
        if not row["Evidence Verification"]:
            df.at[i, "Evidence Verification"] = "Not Required" if row["Request Type"] not in {"Internal OD", "External OD"} else "Evidence Required"
    # Persist CSV-imported rows to the database on first load.
    with db_connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        if count == 0 and not df.empty:
            for _, row in df.iterrows():
                payload = {c: (row[c].isoformat() if isinstance(row[c], date) else str(row[c]) if not pd.isna(row[c]) else "") for c in COLUMNS}
                conn.execute("INSERT OR REPLACE INTO requests(request_id,payload_json) VALUES(?,?)", (str(row['Request ID']), json.dumps(payload)))
            conn.commit()
    return df


def save_data(df):
    init_db()
    out = df.copy()
    # Persist the canonical request records in SQLite.
    with db_connect() as conn:
        conn.execute("DELETE FROM requests")
        for _, row in out.iterrows():
            payload = {}
            for c in COLUMNS:
                value = row[c]
                payload[c] = value.isoformat() if isinstance(value, date) else ("" if pd.isna(value) else str(value))
            conn.execute("INSERT INTO requests(request_id,payload_json) VALUES(?,?)", (str(row['Request ID']), json.dumps(payload)))
        conn.commit()
    # Keep a human-readable CSV backup/export for compatibility with the existing project.
    for c in ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]:
        out[c] = pd.to_datetime(out[c], errors="coerce").dt.strftime("%Y-%m-%d")
    out.to_csv(DATA_FILE, index=False)


def next_id(df):
    nums = []
    for value in df.get("Request ID", pd.Series(dtype=str)).astype(str):
        digits = "".join(x for x in value if x.isdigit())
        if digits:
            nums.append(int(digits))
    return f"EG-{max(nums, default=0) + 1:04d}"


def to_date(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def show_date(value):
    """Format a date safely, including blank/invalid CSV date values."""
    try:
        d = to_date(value)
        if d is None or pd.isna(d):
            return "Not entered"
        return d.strftime("%d %b %Y")
    except (ValueError, TypeError, AttributeError):
        return "Not entered"


def routing_group(request_type):
    if request_type in {"Internal OD", "External OD"}:
        return "OD Monitoring"
    if request_type in {"Bonafide Certificate", "Scholarship Application", "Exam Fee Correction", "ID Card Request", "Transcript Request"}:
        return "Certificates / Admin"
    return "General Requests"


def activity_delta(row):
    activity_date = to_date(row.get("Activity Date"))
    if not activity_date:
        return None
    raw_time = str(row.get("Activity Time", "")).strip()
    try:
        activity_time = datetime.strptime(raw_time, "%H:%M").time() if raw_time else time(23, 59)
    except ValueError:
        activity_time = time(23, 59)
    return datetime.combine(activity_date, activity_time) - datetime.now()


def is_resolved(status):
    return str(status).strip() in {"Accepted", "Completed", "Rejected"}


def priority_for(row):
    if is_resolved(row.get("Status", "")):
        return "Resolved", "This request has a final status recorded."
    delta = activity_delta(row)
    evidence = str(row.get("Evidence Verification", "Evidence Required"))
    if delta is not None and timedelta(0) <= delta <= timedelta(minutes=20):
        mins = max(0, int(delta.total_seconds() // 60))
        reason = f"Activity starts in about {mins} minute(s); the request is unresolved. Review promptly."
        if evidence not in {"Verified", "Not Required"}:
            reason += " Supporting evidence still needs review."
        return "Immediate", reason
    if delta is not None and delta < timedelta(0):
        return "Urgent", "The activity start time has passed while the request is unresolved. Check the status and follow up as appropriate."
    due = to_date(row.get("Expected Due Date"))
    if due:
        days = (due - date.today()).days
        if days < 0:
            return "Overdue", "The expected response date has passed and no final decision is recorded. Follow up with the responsible office."
        if days == 0:
            return "Follow-up", "The expected response date is today. Monitor the request and follow up if no response arrives."
        if days <= 2:
            return "Upcoming", f"The expected response date is in {days} day(s). Keep monitoring the request."
    return "Routine", "No immediate timing issue has been identified from the information entered."


def analyse(row):
    priority, priority_reason = priority_for(row)
    if priority in {"Immediate", "Urgent", "Overdue", "Follow-up"}:
        value = {"Immediate": 95, "Urgent": 85, "Overdue": 75, "Follow-up": 55}.get(priority, 50)
        return {"value": value, "reasons": [priority_reason],
                "actions": ["Review the evidence and request details. An authorised faculty member must make the approval decision."]}
    today = date.today()
    reasons, actions = [], []
    value = 8
    submitted = to_date(row.get("Submission Date"))
    due = to_date(row.get("Expected Due Date"))
    updated = to_date(row.get("Last Updated"))
    status = str(row.get("Status", ""))
    owner = str(row.get("Assigned To", "")).strip()
    notes = str(row.get("Notes", "")).lower()

    if status in {"Accepted", "Completed"}:
        return {"value": 0, "reasons": ["The request is marked as completed."],
                "actions": ["No follow-up is needed unless the requester reports a problem."]}

    if due:
        remaining = (due - today).days
        if remaining < 0:
            value += 48
            reasons.append(f"The expected due date passed {abs(remaining)} day(s) ago.")
            actions.append("Contact the responsible office and ask for an updated completion date.")
        elif remaining == 0:
            value += 28
            reasons.append("The expected due date is today.")
            actions.append("Check with the assigned office whether the request will be completed today.")
        elif remaining <= 3:
            value += 20
            reasons.append(f"The expected due date is {remaining} day(s) away.")
            actions.append("Confirm that the request is on track before the due date.")
        elif remaining <= 7:
            value += 10
            reasons.append("The expected due date is within the next 7 days.")
    else:
        reasons.append("No expected due date has been entered.")
        actions.append("Enter an expected due date to monitor the request against a target.")

    if not owner:
        value += 18
        reasons.append("No responsible staff member or office is assigned.")
        actions.append("Assign a responsible staff member or office.")

    if updated:
        inactive = (today - updated).days
        if inactive >= 14:
            value += 24
            reasons.append(f"There has been no recorded update for {inactive} days.")
            actions.append("Request a status update and check whether the request is waiting on anyone.")
        elif inactive >= 7:
            value += 14
            reasons.append(f"There has been no recorded update for {inactive} days.")
            actions.append("Check whether the request needs a follow-up.")
    else:
        value += 12
        reasons.append("No last-updated date has been recorded.")
        actions.append("Record the most recent update date.")

    if submitted:
        age = (today - submitted).days
        if age >= 14:
            value += 10
            reasons.append(f"The request has been open for {age} days.")
            actions.append("Review the request history and identify the next step.")
    else:
        reasons.append("The submission date is missing.")
        actions.append("Add the original submission date.")

    if status == "Waiting for Information":
        value += 8
        reasons.append("The status says information is awaited.")
        actions.append("Confirm what information is missing and who needs to provide it.")

    keyword_rules = {
        "handover": (("handover", "transfer", "transferred", "change of staff"),
                     "Confirm the current owner and make sure the handover is complete."),
        "missing information": (("missing", "incomplete", "not attached", "document required", "awaiting document"),
                                "Confirm the missing information and share a clear checklist."),
        "blocked process": (("blocked", "stuck", "pending approval", "approval pending"),
                            "Ask the responsible office what approval or step is blocking progress."),
    }
    for label, (words, action) in keyword_rules.items():
        if any(word in notes for word in words):
            value += 8
            reasons.append(f"The notes mention a possible {label} issue.")
            actions.append(action)

    if not reasons:
        reasons = ["No strong warning signs were found in the information entered."]
    if not actions:
        actions = ["Continue monitoring the request and update its status when something changes."]
    return {"value": max(0, min(100, int(value))),
            "reasons": list(dict.fromkeys(reasons)),
            "actions": list(dict.fromkeys(actions))}


# SQLite is the canonical store for accounts and requests.
init_db()

if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None

# Theme-aware CSS: colours inherit Streamlit's active theme variables.
# No separate theme switch is added to the app.
st.markdown("""
<style>
.block-container {padding-top:1.5rem; padding-bottom:3rem; max-width:1250px;}
.eg-hero {padding:1.4rem 1.6rem; border-radius:18px; border:1px solid var(--border-color);
background:var(--secondary-background-color); margin-bottom:1.2rem;}
.eg-eyebrow {color:var(--primary-color); text-transform:uppercase; letter-spacing:.12em;
font-size:.76rem; font-weight:750; margin-bottom:.45rem;}
.eg-title {color:var(--text-color); font-size:clamp(2rem,4vw,3.2rem); font-weight:800; line-height:1.1;}
.eg-subtitle {color:var(--text-color); opacity:.8; font-size:1rem; margin-top:.65rem; max-width:780px;}
.eg-card {border:1px solid var(--border-color); background:var(--secondary-background-color);
border-radius:15px; padding:1rem 1.1rem; height:100%;}
.eg-label {color:var(--text-color); opacity:.75; font-size:.86rem; margin-bottom:.35rem;}
.eg-value {color:var(--text-color); font-size:1.65rem; font-weight:750; overflow-wrap:anywhere;}
.eg-note {color:var(--text-color); opacity:.78; font-size:.88rem;}
div[data-testid="stMetric"] {background:var(--secondary-background-color); border:1px solid var(--border-color);
padding:1rem; border-radius:14px;}
.stButton button, .stDownloadButton button {border-radius:10px;}
button[kind="primary"] {background:var(--primary-color); border-color:var(--primary-color); color:white;}
[data-testid="stSidebar"] {border-right:1px solid var(--border-color);}
</style>
""", unsafe_allow_html=True)


def hero(title, subtitle):
    st.markdown(f"""<div class="eg-hero"><div class="eg-eyebrow">EchoGuard AI</div>
    <div class="eg-title">{title}</div><div class="eg-subtitle">{subtitle}</div></div>""",
    unsafe_allow_html=True)


if not st.session_state.authenticated_user:
    hero("Welcome to EchoGuard AI", "Choose your role, then sign in or create an account using your email.")
    role_label = st.radio("I am a…", ["Student", "Teacher / Faculty"], horizontal=True)
    chosen_role = "student" if role_label == "Student" else "faculty"
    login_tab, signup_tab = st.tabs(["Sign in", "Create account"])

    with login_tab:
        with st.form("login_form"):
            login_email = st.text_input("Email address", key="login_email").strip().lower()
            login_password = st.text_input("Password", type="password", key="login_password")
            submitted_login = st.form_submit_button("Sign in with email", type="primary", use_container_width=True)
        st.button("Continue with Google", disabled=True, use_container_width=True,
                  help="Google sign-in requires OAuth credentials and provider setup; it is not enabled in this local demo.")
        if submitted_login:
            account = get_account(login_email) if login_email else None
            if account and verify_password(login_password, account["password_salt"], account["password_hash"]):
                profile = account["profile"]
                if profile.get("role") != chosen_role:
                    st.error("This email is registered under a different role. Choose the role used when you created the account.")
                else:
                    st.session_state.authenticated_user = {
                        "username": profile["email"], "email": profile["email"],
                        "role": profile["role"], "name": profile.get("name", ""),
                        "department": profile.get("department", "Other"), "profile": profile,
                    }
                    st.rerun()
            else:
                st.error("Email or password not found. If you are new, use Create account.")

    with signup_tab:
        with st.form("signup_form", clear_on_submit=False):
            full_name = st.text_input("Full name")
            signup_email = st.text_input("Email address").strip().lower()
            signup_password = st.text_input("Create password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")
            if chosen_role == "student":
                student_id = st.text_input("Register number / Student ID")
                student_department = st.selectbox("Department", DEPARTMENTS)
                study_year = st.selectbox("Year of study", ["1st year", "2nd year", "3rd year", "4th year"])
                section = st.text_input("Section (optional)")
                faculty_department = ""
                designation = ""
            else:
                faculty_department = st.selectbox("Faculty department", DEPARTMENTS)
                designation = st.selectbox("Designation", ["Faculty", "Class Advisor", "HOD", "OD Coordinator", "Administrative Staff", "Other"])
                student_id = ""
                student_department = faculty_department
                study_year = ""
                section = ""
            signup_submit = st.form_submit_button("Create account", type="primary", use_container_width=True)

        if signup_submit:
            signup_email = signup_email.strip().lower()
            if not full_name.strip():
                st.error("Please enter your full name.")
            elif not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", signup_email):
                st.error("Please enter a valid email address.")
            elif len(signup_password) < 8:
                st.error("Use a password with at least 8 characters.")
            elif signup_password != confirm_password:
                st.error("The passwords do not match.")
            else:
                profile = {
                    "email": signup_email,
                    "role": chosen_role,
                    "name": full_name.strip(),
                    "department": student_department,
                }
                if chosen_role == "student":
                    profile.update({"student_id": student_id.strip(), "year": study_year, "section": section.strip()})
                else:
                    profile.update({"department": faculty_department, "designation": designation})
                if not create_account(profile, signup_password):
                    st.error("This email already has an account. Please sign in instead.")
                else:
                    st.session_state.authenticated_user = {
                        "username": signup_email,
                        "email": signup_email,
                        "role": chosen_role,
                        "name": profile["name"],
                        "department": profile["department"],
                        "profile": profile,
                    }
                    st.success("Account created. Opening your workspace…")
                    st.rerun()

    st.caption("Student and faculty accounts have separate profiles. Accounts and requests are stored in a local SQLite database on the computer running Streamlit.")
    st.stop()

CURRENT_USER = st.session_state.authenticated_user
IS_FACULTY = CURRENT_USER["role"] == "faculty"

if "requests_df" not in st.session_state:
    st.session_state.requests_df = load_data()
if "selected_id" not in st.session_state:
    st.session_state.selected_id = None


def card(label, value):
    st.markdown(f"""<div class="eg-card"><div class="eg-label">{label}</div>
    <div class="eg-value">{value}</div></div>""", unsafe_allow_html=True)


with st.sidebar:
    LOGO_FILE = Path(__file__).with_name("echoguard_logo.png")
    if LOGO_FILE.exists():
        st.image(str(LOGO_FILE), use_container_width=True)
    else:
        st.markdown("## 🛡️ EchoGuard AI")
    st.caption("An early-warning agent for hidden delays")
    st.caption(f"Signed in: {CURRENT_USER['name']} ({CURRENT_USER['role'].title()})")
    st.caption(f"Email: {CURRENT_USER.get('email', '')}")
    if IS_FACULTY:
        st.caption(f"Department: {CURRENT_USER.get('department', 'Other')} · {CURRENT_USER.get('profile', {}).get('designation', 'Faculty')}")
    else:
        student_profile = CURRENT_USER.get("profile", {})
        st.caption(f"Student ID: {student_profile.get('student_id', 'Not entered')}")
        st.caption(f"Department: {CURRENT_USER.get('department', 'Other')} · {student_profile.get('year', '')}")
    pages = ["Dashboard", "Add Request", "Delay Analysis", "Manage Requests", "About"]
    if IS_FACULTY:
        pages.insert(3, "Faculty Monitoring")
    page = st.radio("Navigate", pages, label_visibility="collapsed")
    if st.button("Log out", use_container_width=True):
        st.session_state.authenticated_user = None
        st.rerun()
    st.divider()
    st.caption("Theme: app menu ⋮ → Settings → Theme.")
    st.caption("Accounts and requests are stored in echoguard.db; a CSV backup is also maintained.")

all_requests_df = st.session_state.requests_df
if IS_FACULTY:
    df = all_requests_df.copy()
else:
    df = all_requests_df[all_requests_df["Student Username"].astype(str) == CURRENT_USER["username"]].copy()

if page == "Dashboard":
    hero("See delays before they grow.",
         "Track college requests, spot missing updates, and get a clear next action—without assuming the reason for a delay.")
    today = date.today()
    opened = int((~df["Status"].isin(["Accepted", "Completed", "Rejected"])).sum()) if not df.empty else 0
    completed = int(df["Status"].isin(["Accepted", "Completed"]).sum()) if not df.empty else 0
    analyses = [priority_for(r) for _, r in df.iterrows()] if not df.empty else []
    action_needed = sum(p in {"Immediate", "Urgent", "Overdue", "Follow-up"} for p, _ in analyses)
    overdue = sum(p == "Overdue" for p, _ in analyses)
    cols = st.columns(4)
    for col, label, val in zip(cols, ["Total requests", "Action needed", "Awaiting response", "Resolved"],
                               [len(df), action_needed, opened, completed]):
        with col:
            card(label, str(val))
    st.write("")
    st.subheader("🚨 Action Needed")
    if not df.empty:
        urgent_items = []
        for _, request_row in df.iterrows():
            priority, reason = priority_for(request_row)
            if priority in {"Immediate", "Urgent", "Overdue", "Follow-up"}:
                urgent_items.append(({"Immediate": 0, "Urgent": 1, "Overdue": 2, "Follow-up": 3}.get(priority, 4), request_row, priority, reason))
        urgent_items.sort(key=lambda x: x[0])
        if urgent_items:
            for _, request_row, priority, reason in urgent_items[:8]:
                with st.container(border=True):
                    left, right = st.columns([4, 1])
                    with left:
                        st.markdown(f"**{request_row['Request Type']}** · {request_row['Request ID']}")
                        st.caption(f"Student: {request_row['Student Name'] or 'Not entered'} · Status: {request_row['Status']}")
                        st.write(reason)
                        st.caption(f"Evidence: {request_row['Evidence Verification'] or 'Evidence Required'} · Route: {request_row['Routing Group'] or routing_group(request_row['Request Type'])}")
                    with right:
                        st.markdown(f"### { {'Immediate':'🔴 Immediate','Urgent':'🟠 Urgent','Overdue':'🟠 Overdue','Follow-up':'🟡 Follow-up'}.get(priority, priority) }")
        else:
            st.success("No requests currently require immediate follow-up.")
    if df.empty:
        st.info("Your workspace is empty. Add your first request to begin analysing delays.")
        st.markdown("**How it works**\n1. Enter a request and its expected due date.\n2. Add the responsible office and latest update date.\n3. Review the indicator, reasons, and suggested next actions.")
    else:
        st.subheader("Recently added requests")
        recent = df.tail(8).iloc[::-1].copy()
        date_columns = [
            "Submission Date", "Expected Due Date", "Last Updated",
            "Activity Date", "College Response Date"
        ]
        for c in date_columns:
            if c in recent.columns:
                recent[c] = recent[c].apply(show_date)
        recent = recent.astype(str)
        st.dataframe(recent, use_container_width=True, hide_index=True)

elif page == "Add Request":
    hero("Add a request", "Submit a student request and keep evidence, activity timing and response expectations together.")
    st.caption("Expected due date is the date you hope to receive a response; it is not a guaranteed college deadline.")
    with st.form("add_form", clear_on_submit=True):
        a, b = st.columns(2)
        with a:
            student_name = st.text_input("Student name", value=CURRENT_USER["name"] if not IS_FACULTY else "")
            department = st.selectbox("Department", DEPARTMENTS)
            type_choice = st.selectbox("Request type", TYPES)
            custom_type = st.text_input("Enter request type") if type_choice == "Other" else ""
            submitted_date = st.date_input("Date request was submitted to college", value=date.today())
            due_date = st.date_input("Expected date for college approval or response", value=date.today())
        with b:
            status = st.selectbox("Current request status", STATUSES)
            owner = st.text_input("Assigned staff / office (if known)", placeholder="e.g. OD coordinator / Student Affairs")
            updated = st.date_input("Last updated date", value=date.today())
        is_od = type_choice in {"Internal OD", "External OD"}
        st.markdown("#### Activity details")
        if is_od:
            c, d = st.columns(2)
            with c:
                activity_name = st.text_input("Event / activity name")
                activity_date = st.date_input("Date of event or activity", value=date.today())
            with d:
                activity_time = st.time_input("Activity start time (if known)", value=(datetime.now() + timedelta(minutes=30)).time().replace(second=0, microsecond=0))
                evidence_file = st.file_uploader("Supporting evidence (required for OD)", type=["pdf", "png", "jpg", "jpeg"], help="For example, registration confirmation, official invitation or organiser confirmation.")
        else:
            activity_name, activity_date, activity_time = "", None, None
            evidence_file = st.file_uploader("Supporting evidence (optional)", type=["pdf", "png", "jpg", "jpeg"])
        notes = st.text_area("Purpose / notes", placeholder="Add context or details that help the reviewer.", height=100)
        save = st.form_submit_button("Save request", type="primary", use_container_width=True)
    if save:
        req_type = custom_type.strip() if type_choice == "Other" else type_choice
        if not req_type:
            st.error("Please enter the request type.")
        elif due_date < submitted_date:
            st.error("Expected response date cannot be earlier than the submission date.")
        elif updated < submitted_date:
            st.error("Last updated date cannot be earlier than the submission date.")
        elif is_od and not student_name.strip():
            st.error("Please enter the student's name for an OD request.")
        elif is_od and not activity_name.strip():
            st.error("Please enter the event or activity name.")
        elif is_od and evidence_file is None:
            st.error("Please upload supporting evidence for this OD request.")
        else:
            current = st.session_state.requests_df.copy()
            request_id = next_id(current)
            evidence_status = "Pending Verification" if evidence_file else ("Evidence Required" if is_od else "Not Required")
            stored_evidence_name = ""
            if evidence_file:
                # The browser's file picker works on both laptops and phones.
                # Save the uploaded bytes on the computer/server running Streamlit.
                safe_original = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(evidence_file.name).name).strip("._") or "evidence"
                stored_evidence_name = f"{request_id}_{safe_original}"
                (EVIDENCE_DIR / stored_evidence_name).write_bytes(evidence_file.getvalue())
            new_row = {"Request ID": request_id, "Request Type": req_type,
                       "Submission Date": submitted_date, "Expected Due Date": due_date,
                       "Status": status, "Assigned To": owner.strip(), "Last Updated": updated,
                       "Notes": notes.strip(), "Student Name": student_name.strip(),
                       "Activity Name": activity_name.strip(), "Activity Date": activity_date,
                       "Activity Time": activity_time.strftime("%H:%M") if activity_time else "",
                       "Evidence File Name": stored_evidence_name,
                       "Evidence Verification": evidence_status, "Routing Group": routing_group(req_type),
                        "Faculty Notes": "", "College Response Date": "", "Department": department,
                       "Student Username": CURRENT_USER["username"] if not IS_FACULTY else ""}
            current = pd.concat([current, pd.DataFrame([new_row])], ignore_index=True)
            st.session_state.requests_df = current
            save_data(current)
            st.session_state.selected_id = new_row["Request ID"]
            st.success(f"Request {new_row['Request ID']} saved successfully.")
            if evidence_file:
                st.info("Evidence uploaded and saved on the Streamlit host in the evidence_uploads folder. Faculty can download it from the review section.")

elif page == "Delay Analysis":
    hero("Analyse a request", "Each request is checked individually. The percentage is an experimental rule-based indicator, not a proven probability.")
    if df.empty:
        st.info("No requests to analyse yet. Add a request first.")
    else:
        ids = df["Request ID"].astype(str).tolist()
        current_id = st.session_state.selected_id
        default = ids.index(current_id) if current_id in ids else 0
        selected = st.selectbox("Choose a request", ids, index=default,
            format_func=lambda rid: f"{rid} · {df.loc[df['Request ID'].astype(str) == rid, 'Request Type'].iloc[0]}")
        row = df[df["Request ID"].astype(str) == selected].iloc[0]
        result = analyse(row)
        left, right = st.columns([1, 1.5], gap="large")
        with left:
            st.markdown("### Delay indicator")
            st.markdown(f"""<div class="eg-card"><div class="eg-label">Experimental delay indicator</div>
            <div class="eg-value" style="font-size:3.2rem;">{result['value']}%</div>
            <div class="eg-note">Rule-based prototype signal; not a calibrated probability.</div></div>""",
            unsafe_allow_html=True)
            st.write("")
            st.markdown("**Request details**")
            st.write(f"**Type:** {row['Request Type']}")
            st.write(f"**Status:** {row['Status']}")
            st.write(f"**Submitted:** {show_date(row['Submission Date'])}")
            st.write(f"**Expected due:** {show_date(row['Expected Due Date'])}")
            st.write(f"**Assigned to:** {row['Assigned To'] or 'Not assigned'}")
            st.write(f"**Last updated:** {show_date(row['Last Updated'])}")
        with right:
            st.markdown("### Why was this flagged?")
            for reason in result["reasons"]:
                st.markdown(f"- {reason}")
            st.markdown("### Recommended action")
            for action in result["actions"]:
                st.markdown(f"- {action}")
        with st.expander("Draft a follow-up message"):
            office = str(row["Assigned To"]).strip() or "the responsible office"
            draft = (f"Hello {office},\n\nI am following up on '{row['Request Type']}' "
                     f"(reference {row['Request ID']}), submitted on {show_date(row['Submission Date'])}. "
                     f"The expected due date is {show_date(row['Expected Due Date'])}. "
                     "Could you please share the current status and let me know if any additional information is needed?\n\nThank you.")
            st.text_area("Review this message before sending", value=draft, height=180)

elif page == "Faculty Monitoring":
    if not IS_FACULTY:
        st.error("Faculty access required.")
        st.stop()
    # Faculty works against the complete request list, not the student's filtered view.
    df = st.session_state.requests_df.copy()
    hero("Faculty monitoring", "A central view for spotting urgent requests and routing them to the appropriate review group.")
    st.warning("Prototype: this page has no login or role-based access control yet. Do not use it for real student records until secure access is implemented.")
    df = st.session_state.requests_df
    if df.empty:
        st.info("No requests have been submitted yet.")
    else:
        active = df[~df["Status"].apply(is_resolved)].copy()
        if not active.empty:
            active["Priority"] = active.apply(lambda r: priority_for(r)[0], axis=1)
            active["Priority reason"] = active.apply(lambda r: priority_for(r)[1], axis=1)
            active["Routing Group"] = active.apply(lambda r: r["Routing Group"] or routing_group(r["Request Type"]), axis=1)
            active["_order"] = active["Priority"].map({"Immediate": 0, "Urgent": 1, "Overdue": 2, "Follow-up": 3, "Upcoming": 4, "Routine": 5}).fillna(6)
            active = active.sort_values("_order")
        x, y, z = st.columns(3)
        x.metric("Unresolved requests", len(active))
        y.metric("Immediate / urgent", int(active["Priority"].isin(["Immediate", "Urgent"]).sum()) if not active.empty else 0)
        z.metric("Evidence awaiting review", int(active["Evidence Verification"].isin(["Pending Verification", "AI Review", "Evidence Required"]).sum()) if not active.empty else 0)
        route = st.selectbox("Route by category", ["All categories", "OD Monitoring", "Certificates / Admin", "General Requests"])
        view = active if route == "All categories" or active.empty else active[active["Routing Group"] == route]
        if view.empty:
            st.success("No unresolved requests in this category.")
        else:
            st.dataframe(view[["Request ID", "Student Name", "Department", "Request Type", "Activity Name", "Activity Date", "Activity Time", "Evidence File Name", "Evidence Verification", "Status", "Priority", "Routing Group"]], use_container_width=True, hide_index=True)
            st.subheader("Review a request")
            chosen = st.selectbox("Select request", view["Request ID"].astype(str).tolist(), key="faculty_review_id")
            row = view[view["Request ID"].astype(str) == chosen].iloc[0]
            st.write(f"**Student:** {row['Student Name'] or 'Not entered'} · **Department:** {row.get('Department', 'Not entered') or 'Not entered'}")
            st.write(f"**Request:** {row['Request Type']} — {row['Activity Name'] or row['Request Type']}")
            st.write(f"**Priority reason:** {row['Priority reason']}")
            st.write(f"**Evidence filename:** {Path(str(row['Evidence File Name'])).name if row['Evidence File Name'] else 'No filename recorded'}")
            st.write(f"**Evidence verification:** {row['Evidence Verification'] or 'Evidence Required'}")
            evidence_name = str(row.get("Evidence File Name", "")).strip()
            evidence_path = EVIDENCE_DIR / Path(evidence_name).name if evidence_name else None
            if evidence_path and evidence_path.is_file():
                mime = "application/pdf" if evidence_path.suffix.lower() == ".pdf" else "image/" + evidence_path.suffix.lower().lstrip(".")
                st.download_button("Download supporting evidence", data=evidence_path.read_bytes(),
                                   file_name=evidence_path.name, mime=mime, key=f"evidence_{chosen}")
                if evidence_path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                    st.image(str(evidence_path), caption="Uploaded supporting evidence", use_container_width=True)
            elif evidence_name:
                st.warning("Evidence file is referenced in the CSV, but the file is not present in evidence_uploads on this computer/server.")
            st.markdown("### Faculty response")
            st.caption("Choose a decision/status and save it here. This records the faculty response immediately in the prototype; it does not send a push notification to the student.")
            status_options = STATUSES
            current_status = str(row.get("Status", "Submitted"))
            with st.form(f"faculty_response_{chosen}"):
                new_status = st.selectbox("Decision / request status", status_options,
                    index=status_options.index(current_status) if current_status in status_options else 0)
                new_evidence_status = st.selectbox("Evidence verification", EVIDENCE_STATUSES,
                    index=EVIDENCE_STATUSES.index(str(row.get("Evidence Verification", "Pending Verification"))) if str(row.get("Evidence Verification", "Pending Verification")) in EVIDENCE_STATUSES else 0)
                response_note = st.text_area("Response / faculty notes", value=str(row.get("Faculty Notes", "")),
                    placeholder="e.g. OD approved; please collect signed form from the office.")
                response_now = st.form_submit_button("Submit faculty response", type="primary", use_container_width=True)
            if response_now:
                current = st.session_state.requests_df.copy()
                idx = current.index[current["Request ID"].astype(str) == chosen][0]
                current.loc[idx, "Status"] = new_status
                current.loc[idx, "Evidence Verification"] = new_evidence_status
                current.loc[idx, "Faculty Notes"] = response_note.strip()
                current.loc[idx, "Last Updated"] = pd.Timestamp(date.today())
                current.loc[idx, "College Response Date"] = pd.Timestamp(date.today())
                st.session_state.requests_df = current
                save_data(current)
                st.success(f"Faculty response saved for {chosen}. Evidence verification and approval status are recorded separately.")
                st.rerun()
            st.info("AI checking, secure role-based access and automatic notifications still need integration. Faculty must make the actual approval decision; AI should not approve automatically.")

elif page == "Manage Requests":
    hero("Manage requests", "Edit entries, delete test data, or import and export CSV files.")
    df = st.session_state.requests_df
    if df.empty:
        st.info("There are no requests yet. Add one or import a CSV file.")
    else:
        # Use a display-only copy so mixed date / datetime values do not crash
        # Streamlit's Arrow table conversion. The underlying request data is unchanged.
        display_df = df.copy()
        display_date_columns = [
            "Submission Date", "Expected Due Date", "Last Updated",
            "Activity Date", "College Response Date"
        ]
        for col in display_date_columns:
            if col in display_df.columns:
                display_df[col] = display_df[col].apply(show_date)
        display_df = display_df.fillna("").astype(str)
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        st.subheader("Edit a request")
        ids = df["Request ID"].astype(str).tolist()
        selected = st.selectbox("Select request", ids, key="edit_id")
        row = df[df["Request ID"].astype(str) == selected].iloc[0]
        with st.form("edit_form"):
            a, b = st.columns(2)
            with a:
                req_type = st.text_input("Request type", value=str(row["Request Type"]))
                dept_current = str(row.get("Department", "Other"))
                department = st.selectbox("Department", DEPARTMENTS, index=DEPARTMENTS.index(dept_current) if dept_current in DEPARTMENTS else 0, key="edit_department")
                submitted_date = st.date_input("Submission date", value=to_date(row["Submission Date"]) or date.today(), key="ed_sub")
                due_date = st.date_input("Expected due date", value=to_date(row["Expected Due Date"]) or date.today(), key="ed_due")
                old_status = str(row["Status"])
                if IS_FACULTY:
                    status = st.selectbox("Status", STATUSES, index=STATUSES.index(old_status) if old_status in STATUSES else 0)
                else:
                    status = old_status
                    st.caption(f"Current status (faculty-managed): **{old_status}**")
            with b:
                owner = st.text_input("Assigned staff / office", value=str(row["Assigned To"]))
                updated = st.date_input("Last updated date", value=to_date(row["Last Updated"]) or date.today(), key="ed_upd")
                notes = st.text_area("Notes", value=str(row["Notes"]), height=130)
            update = st.form_submit_button("Save changes", type="primary", use_container_width=True)
        if update:
            if not req_type.strip():
                st.error("Request type cannot be empty.")
            elif due_date < submitted_date or updated < submitted_date:
                st.error("Due date and last-updated date must not be earlier than the submission date.")
            else:
                current = st.session_state.requests_df.copy()
                idx = current.index[current["Request ID"].astype(str) == selected][0]
                for col, val in {"Request Type": req_type.strip(), "Department": department, "Submission Date": submitted_date,
                                 "Expected Due Date": due_date, "Status": status, "Assigned To": owner.strip(),
                                 "Last Updated": updated, "Notes": notes.strip()}.items():
                    current.loc[idx, col] = val
                st.session_state.requests_df = current
                save_data(current)
                st.success("Request updated.")
                st.rerun()
        if IS_FACULTY:
            st.subheader("Evidence and faculty review")
            with st.form("review_fields_form"):
                ev_current = str(row.get("Evidence Verification", "Evidence Required"))
                ev_index = EVIDENCE_STATUSES.index(ev_current) if ev_current in EVIDENCE_STATUSES else 0
                evidence_status = st.selectbox("Evidence verification status", EVIDENCE_STATUSES, index=ev_index)
                faculty_notes = st.text_area("Faculty / review notes", value=str(row.get("Faculty Notes", "")))
                review_save = st.form_submit_button("Save review details", type="primary")
            if review_save:
                current = st.session_state.requests_df.copy()
                idx = current.index[current["Request ID"].astype(str) == selected][0]
                current.loc[idx, "Evidence Verification"] = evidence_status
                current.loc[idx, "Faculty Notes"] = faculty_notes.strip()
                if str(current.loc[idx, "Status"]) in {"Accepted", "Completed", "Rejected"}:
                    current.loc[idx, "College Response Date"] = pd.Timestamp(date.today())
                st.session_state.requests_df = current
                save_data(current)
                st.success("Evidence/review details saved.")
                st.rerun()

        if IS_FACULTY:
            st.subheader("Delete a request")
            confirm = st.checkbox(f"I want to permanently delete {selected}", key="confirm_delete")
        else:
            confirm = False
        if IS_FACULTY and st.button("Delete selected request", disabled=not confirm):
            current = st.session_state.requests_df
            current = current[current["Request ID"].astype(str) != selected].copy()
            st.session_state.requests_df = current
            save_data(current)
            st.success(f"{selected} deleted.")
            st.rerun()

    st.divider()
    st.subheader("Import / export")
    current = st.session_state.requests_df.copy()
    export_df = current.copy()
    for c in ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]:
        export_df[c] = pd.to_datetime(export_df[c], errors="coerce").dt.strftime("%Y-%m-%d")
    st.download_button("Download requests as CSV", export_df.to_csv(index=False).encode("utf-8"),
                       "echoguard_requests.csv", "text/csv", use_container_width=True)
    uploaded = st.file_uploader("Import requests from CSV", type=["csv"])
    method = st.radio("Import method", ["Add imported rows", "Replace current requests"], horizontal=True)
    if uploaded is not None:
        try:
            incoming = pd.read_csv(uploaded, dtype={"Request ID": str})
            missing = [c for c in COLUMNS if c not in incoming.columns]
            if missing:
                st.error("CSV is missing these columns: " + ", ".join(missing))
            else:
                incoming = incoming[COLUMNS].copy()
                for c in ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]:
                    incoming[c] = pd.to_datetime(incoming[c], errors="coerce").dt.date
                for c in ["Request ID", "Request Type", "Status", "Assigned To", "Notes"]:
                    incoming[c] = incoming[c].fillna("").astype(str)
                st.caption(f"{len(incoming)} row(s) found.")
                if st.button("Import CSV", type="primary"):
                    if method == "Replace current requests":
                        result = incoming
                    else:
                        result = st.session_state.requests_df.copy()
                        for _, incoming_row in incoming.iterrows():
                            item = incoming_row.to_dict()
                            if not item["Request ID"].strip() or item["Request ID"] in set(result["Request ID"].astype(str)):
                                item["Request ID"] = next_id(result)
                            result = pd.concat([result, pd.DataFrame([item])], ignore_index=True)
                    st.session_state.requests_df = result[COLUMNS]
                    save_data(st.session_state.requests_df)
                    st.success("CSV imported and saved.")
                    st.rerun()
        except Exception as exc:
            st.error(f"Could not import this CSV: {exc}")

elif page == "About":
    hero("About EchoGuard AI", "A student prototype for spotting possible delay signals in college request workflows.")
    st.markdown("""
### The problem
Requests may be delayed when a due date passes, ownership is unclear, updates stop, or a handover or missing document is mentioned.

### What it does
- Stores requests entered by the user; no sample requests are preloaded.
- Separates internal OD, external OD and certificate/admin requests.
- Flags unresolved activities starting within 20 minutes for immediate review.
- Tracks supporting-evidence status separately from college approval.
- Provides a faculty monitoring view with category-based routing.
- Checks visible, rule-based warning signs.
- Shows one experimental delay-indicator percentage for each request.
- Explains warning signs and suggests next actions.
- Drafts a follow-up message for a person to review.

### Important limitation
The percentage is **not a validated probability**. It is an experimental prototype indicator based on hand-written rules. A genuine probability estimate would require suitable historical requests, known outcomes, and model validation.

### Privacy and storage
Data is saved in `echoguard_requests.csv` beside `app.py` on the computer running Streamlit. Evidence uploads are saved in an `evidence_uploads` folder on the computer/server running Streamlit. This is suitable only for a local demo; secure access controls, protected storage, AI document checking, role-based permissions and notifications must be implemented before real deployment. Use fictional data for presentations and do not enter sensitive student details. This local CSV is not a secure multi-user database.
""")

st.divider()
st.caption("EchoGuard AI · Student prototype · Review suggested actions before acting on them.")
