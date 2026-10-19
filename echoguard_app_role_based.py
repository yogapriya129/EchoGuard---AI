"""
EchoGuard AI — Role-Based Request Management Frontend (Prototype)

PURPOSE
    A Streamlit prototype for recording and monitoring college requests and
    highlighting possible delay signals using transparent, hand-written rules.

INCLUDED PAGES
    1. Dashboard            — overview of stored requests and current statuses.
    2. Add Request          — enter request/activity details and evidence status.
    3. Request Tracking     — search/filter requests and inspect request details.
    4. Delay Analysis       — rule-based warning signs and follow-up drafts.
    5. Faculty Monitoring   — category routing and a monitoring view.
    6. Manage Requests      — edit/manage records and import/export CSV data.
    7. About                — project purpose, features, limits, and privacy notes.

TECHNOLOGY
    Python, Streamlit, and pandas. Records are stored locally in
    echoguard_requests.csv, created beside this Python file on first run.

RUNNING THE PROTOTYPE
    1. Install dependencies:  pip install streamlit pandas
    2. Open a terminal in this file's folder.
    3. Run:                   streamlit run app.py

IMPORTANT LIMITATIONS
    - This is a prototype, not a secure production system.
    - The delay indicator is experimental and rule-based, not a validated AI
      probability or trained machine-learning prediction.
    - Student and Teacher accounts use backend-stored password hashes; this local prototype still needs a security review before public deployment.
    - Evidence uploads are not securely stored here; the prototype records a
      filename/status rather than implementing secure document storage.
    - The SQLite backend is integrated. No AI Engineering module is used. Production-grade deployment security and notifications are not included.
    - Use fictional demo records; do not enter sensitive real student data.

This header documents the code's intended scope; it does not claim that planned
integrations are implemented.
"""

from pathlib import Path
from datetime import date, datetime, time, timedelta
import pandas as pd
import streamlit as st
import echoguard_backend as backend

st.set_page_config(page_title="EchoGuard AI", page_icon="🛡️", layout="wide")

DATA_FILE = Path(__file__).with_name("echoguard_requests.csv")
COLUMNS = [
    "Request ID", "Request Type", "Submission Date", "Expected Due Date",
    "Status", "Assigned To", "Last Updated", "Notes", "Student Name",
    "Activity Name", "Activity Date", "Activity Time", "Evidence File Name",
    "Evidence Verification", "Routing Group", "Faculty Notes", "College Response Date"
]
STATUSES = ["Submitted", "Under Review", "Waiting for Information", "In Progress", "Accepted", "Completed", "Rejected"]
TYPES = ["Internal OD", "External OD", "Bonafide Certificate", "Scholarship Application",
         "Exam Fee Correction", "ID Card Request", "Transcript Request", "Other"]
EVIDENCE_STATUSES = ["Evidence Required", "Pending Verification", "Verified", "Verification Issue", "Not Required"]


def blank_data():
    return pd.DataFrame(columns=COLUMNS)


def load_data():
    """Load requests from SQLite, migrating the legacy CSV once if needed."""
    try:
        backend.migrate_csv_once(DATA_FILE)
        df = backend.load_requests()
        for c in COLUMNS:
            if c not in df:
                df[c] = ""
        df = df[COLUMNS]
        date_cols = ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]
        # Keep dates as ISO strings in the DataFrame. pandas 3.x may infer
        # datetime64 from mixed date/blank values, which rejects Python date
        # assignments later in edit/review forms and can leak NaT into display.
        for c in date_cols:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.strftime("%Y-%m-%d").fillna("").astype(object)
        for c in COLUMNS:
            if c not in date_cols:
                df[c] = df[c].fillna("").astype(str)
        for i, row in df.iterrows():
            if not row["Routing Group"]:
                df.at[i, "Routing Group"] = routing_group(row["Request Type"])
            if not row["Evidence Verification"]:
                df.at[i, "Evidence Verification"] = "Not Required" if row["Request Type"] not in {"Internal OD", "External OD"} else "Evidence Required"
        return df
    except Exception as exc:
        st.error("Could not load EchoGuard AI data from SQLite. Existing database/CSV data has not been intentionally replaced.")
        st.caption(f"Technical detail: {type(exc).__name__}: {exc}")
        st.stop()


def save_data(df, note=""):
    """Persist request data through the backend; student saves preserve other users' records."""
    try:
        if st.session_state.get("user_role") == "Student":
            all_rows = backend.load_requests()
            owner = st.session_state.get("display_name", "").casefold()
            # df is the full table in session state. Keep other students' rows once,
            # then append only this student's rows; appending all of df duplicates IDs.
            names = df["Student Name"].astype(str).str.strip().str.casefold()
            own_rows = df[names == owner].copy()
            all_names = all_rows["Student Name"].astype(str).str.strip().str.casefold()
            others = all_rows[all_names != owner].copy()
            combined = pd.concat([others, own_rows], ignore_index=True)
            backend.save_requests(combined, changed_by=st.session_state.get("display_name", "Student"), changed_role="Student", note=note)
        else:
            backend.save_requests(df, changed_by=st.session_state.get("display_name", "User"), changed_role=st.session_state.get("user_role", "System"), note=note)
    except Exception as exc:
        st.error("Could not save request changes to echoguard.db. Please check the data and try again.")
        st.caption(f"Technical detail: {type(exc).__name__}: {exc}")
        raise


def next_id(df):
    nums = []
    for value in df.get("Request ID", pd.Series(dtype=str)).astype(str):
        digits = "".join(x for x in value if x.isdigit())
        if digits:
            nums.append(int(digits))
    return f"EG-{max(nums, default=0) + 1:04d}"


def to_date(value):
    """Return a real datetime.date or None; never pass pandas NaT onward."""
    if value is None:
        return None
    # Check pandas missing sentinels BEFORE date/datetime type checks. In some
    # pandas versions NaT behaves like a datetime-like object but strftime fails.
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
        if not isinstance(missing, (list, tuple)) and bool(missing):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    # Do not accept NaTType merely because some pandas versions treat it as date-like.
    if type(value).__name__ == "NaTType":
        return None
    if isinstance(value, date):
        return value
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except (TypeError, ValueError, OverflowError, AttributeError):
        return None


def show_date(value):
    d = to_date(value)
    # Extra guard for NaT-like values in legacy/corrupted rows.
    if d is None or type(d).__name__ == "NaTType":
        return "Not entered"
    try:
        return d.strftime("%d %b %Y")
    except (TypeError, ValueError, AttributeError):
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
    return str(status).strip() in {"Completed", "Rejected"}


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

    if status in {"Completed", "Rejected"}:
        label = "completed" if status == "Completed" else "rejected"
        return {"value": 0, "reasons": [f"The request is marked as {label}."],
                "actions": ["No routine follow-up is needed unless the requester disputes the outcome or reports a problem."]}

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


# ---------------------- STUDENT / TEACHER LOGIN & SELF-REGISTRATION ----------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_role" not in st.session_state:
    st.session_state.user_role = ""
if "username" not in st.session_state:
    st.session_state.username = ""
if "display_name" not in st.session_state:
    st.session_state.display_name = ""

if not st.session_state.authenticated:
    st.markdown("## 🛡️ EchoGuard AI")
    st.markdown("### Student and Teacher Portal")
    st.write("Create your own account or sign in. Student and Teacher accounts are registered separately.")
    login_tab, signup_tab = st.tabs(["Login", "Create account"] )
    with login_tab:
        with st.form("echoguard_login_form"):
            login_username = st.text_input("Username", key="login_username")
            login_password = st.text_input("Password", type="password", key="login_password")
            login_role = st.selectbox("Sign in as", ["Student", "Teacher"], key="login_role")
            login_submit = st.form_submit_button("Login", type="primary", use_container_width=True)
        if login_submit:
            user = backend.authenticate_user(login_username, login_password)
            if user and user["role"] == login_role:
                st.session_state.authenticated = True
                st.session_state.username = user["username"]
                st.session_state.display_name = user["display_name"]
                st.session_state.user_role = user["role"]
                st.session_state.page_after_login = "Dashboard"
                st.rerun()
            elif user:
                st.error("This account belongs to a different role. Choose the correct account type.")
            else:
                st.error("Invalid username or password.")
    with signup_tab:
        st.info("Create a Student account to submit and track your own requests, or a Teacher account to review requests.")
        with st.form("echoguard_signup_form", clear_on_submit=True):
            new_role = st.selectbox("Create account type", ["Student", "Teacher"], key="signup_role")
            full_name = st.text_input("Full name", key="signup_full_name")
            new_username = st.text_input("Choose username", key="signup_username", help="3–32 characters: letters, numbers, dot, underscore or hyphen")
            new_password = st.text_input("Create password", type="password", key="signup_password", help="At least 8 characters")
            confirm_password = st.text_input("Confirm password", type="password", key="signup_confirm_password")
            signup_submit = st.form_submit_button("Create account", type="primary", use_container_width=True)
        if signup_submit:
            if new_password != confirm_password:
                st.error("Passwords do not match.")
            else:
                try:
                    created = backend.register_user(new_username, full_name, new_role, new_password)
                    st.success(f"{created['role']} account created for '{created['username']}'. Go to Login and sign in.")
                except Exception as exc:
                    st.error(str(exc))
    st.caption("Accounts are stored locally in SQLite. Use a unique password; this prototype is not yet production-hardened.")
    st.stop()

# Initialise application data only after the demo login gate.


if "requests_df" not in st.session_state:
    st.session_state.requests_df = load_data()
if "selected_id" not in st.session_state:
    st.session_state.selected_id = None

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
    st.caption(f"Signed in as **{st.session_state.username}** · {st.session_state.user_role}")
    role_pages = {
        "Student": ["Dashboard", "Add Request", "Request Tracking", "About"],
        "Teacher": ["Dashboard", "Request Tracking", "Delay Analysis", "Faculty Monitoring", "About"],
        "Faculty": ["Dashboard", "Request Tracking", "Delay Analysis", "Faculty Monitoring", "About"],
        "Admin": ["Dashboard", "Add Request", "Request Tracking", "Delay Analysis", "Faculty Monitoring", "Manage Requests", "About"],
    }
    available_pages = role_pages.get(st.session_state.user_role, ["Dashboard", "About"])
    default_page = st.session_state.pop("page_after_login", available_pages[0])
    default_index = available_pages.index(default_page) if default_page in available_pages else 0
    page = st.radio("Navigate", available_pages, index=default_index, label_visibility="collapsed")
    st.divider()
    if st.button("Log out", use_container_width=True):
        for key in ["authenticated", "user_role", "username", "page_after_login"]:
            st.session_state.pop(key, None)
        st.rerun()
    st.caption("Theme: app menu ⋮ → Settings → Theme.")
    st.caption("Prototype data is saved locally to SQLite.")

df = st.session_state.requests_df

if page == "Dashboard":
    hero("See delays before they grow.",
         "Track college requests, spot missing updates, and get a clear next action—without assuming the reason for a delay.")
    today = date.today()
    opened = int((~df["Status"].isin(["Completed", "Rejected"])).sum()) if not df.empty else 0
    completed = int((df["Status"] == "Completed").sum()) if not df.empty else 0
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
        for c in ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]:
            recent[c] = recent[c].apply(show_date)
        st.dataframe(recent, use_container_width=True, hide_index=True)

elif page == "Add Request":
    hero("Add a request", "Submit a student request and keep evidence, activity timing and response expectations together.")
    st.caption("Expected due date is the date you hope to receive a response; it is not a guaranteed college deadline.")
    with st.form("add_form", clear_on_submit=True):
        a, b = st.columns(2)
        with a:
            if st.session_state.get("user_role") == "Student":
                student_name = st.text_input(
                    "Student name", value=st.session_state.get("display_name", ""), disabled=True
                )
            else:
                student_name = st.text_input("Student name")
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
            for date_col in ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]:
                if date_col in current.columns:
                    current[date_col] = current[date_col].astype(object)
            evidence_status = "Pending Verification" if evidence_file else ("Evidence Required" if is_od else "Not Required")
            new_row = {"Request ID": next_id(current), "Request Type": req_type,
                       "Submission Date": submitted_date, "Expected Due Date": due_date,
                       "Status": status, "Assigned To": owner.strip(), "Last Updated": updated,
                       "Notes": notes.strip(), "Student Name": student_name.strip(),
                       "Activity Name": activity_name.strip(), "Activity Date": activity_date,
                       "Activity Time": activity_time.strftime("%H:%M") if activity_time else "",
                       "Evidence File Name": evidence_file.name if evidence_file else "",
                       "Evidence Verification": evidence_status, "Routing Group": routing_group(req_type),
                       "Faculty Notes": "", "College Response Date": ""}
            # Store uploaded evidence locally. This does not authenticate the document.
            if evidence_file:
                try:
                    saved_evidence_name = backend.save_evidence(evidence_file, new_row["Request ID"])
                    new_row["Evidence File Name"] = saved_evidence_name
                except Exception as exc:
                    st.error(f"Could not save the evidence file: {exc}")
                    st.stop()

            current = pd.concat([current, pd.DataFrame([new_row])], ignore_index=True)
            st.session_state.requests_df = current
            save_data(current)
            st.session_state.selected_id = new_row["Request ID"]
            st.success(f"Request {new_row['Request ID']} saved successfully.")

            if evidence_file:
                st.markdown("#### Evidence review")
                st.info(
                    "Evidence was saved. No automatic document analysis is used. "
                    "An authorised faculty member must inspect the original file and update its verification status manually."
                )


elif page == "Request Tracking":
    hero("Track a request", "Find a request, check its latest status, and review the dates and evidence information recorded in the prototype.")
    if df.empty:
        st.info("No requests to track yet. Add a request first.")
    else:
        search_col, status_col = st.columns([2, 1])
        with search_col:
            search_text = st.text_input("Search by request ID, student, or request type", placeholder="e.g. EG-0001 or scholarship")
        with status_col:
            status_filter = st.selectbox("Filter by status", ["All statuses"] + STATUSES)
        tracked = df.copy()
        if search_text.strip():
            needle = search_text.strip().casefold()
            searchable = tracked[["Request ID", "Student Name", "Request Type"]].astype(str).apply(
                lambda col: col.str.casefold().str.contains(needle, regex=False)
            ).any(axis=1)
            tracked = tracked[searchable]
        if status_filter != "All statuses":
            tracked = tracked[tracked["Status"] == status_filter]
        st.caption(f"Showing {len(tracked)} of {len(df)} recorded requests.")
        if tracked.empty:
            st.warning("No requests match those filters. Try another search or status.")
        else:
            display = tracked[["Request ID", "Request Type", "Student Name", "Submission Date", "Expected Due Date", "Status", "Evidence Verification", "Last Updated"]].copy()
            for date_col in ["Submission Date", "Expected Due Date", "Last Updated"]:
                display[date_col] = display[date_col].apply(show_date)
            st.dataframe(display, use_container_width=True, hide_index=True)
            chosen_id = st.selectbox("View request details", tracked["Request ID"].astype(str).tolist(), key="tracking_request_id")
            row = tracked[tracked["Request ID"].astype(str) == chosen_id].iloc[0]
            st.subheader(f"Request {row['Request ID']}")
            a, b, c = st.columns(3)
            with a:
                st.markdown("**Request type**")
                st.write(row["Request Type"])
                st.markdown("**Current status**")
                st.write(row["Status"])
            with b:
                st.markdown("**Submitted**")
                st.write(show_date(row["Submission Date"]))
                st.markdown("**Expected response date**")
                st.write(show_date(row["Expected Due Date"]))
            with c:
                st.markdown("**Assigned office**")
                st.write(row["Assigned To"] or "Not assigned")
                st.markdown("**Last updated**")
                st.write(show_date(row["Last Updated"]))
            st.markdown("**Evidence status**")
            st.write(row["Evidence Verification"] or "Not recorded")
            if row["Evidence File Name"]:
                st.markdown("**Evidence filename**")
                st.write(row["Evidence File Name"])
            if row["Notes"]:
                st.markdown("**Latest notes**")
                st.write(row["Notes"])
            if row["Faculty Notes"]:
                st.markdown("**Faculty notes**")
                st.write(row["Faculty Notes"])
            st.subheader("Request status timeline")
            try:
                history = backend.get_status_history(str(chosen_id))
                if history.empty:
                    st.caption("No status changes have been recorded yet. New changes will appear here.")
                else:
                    st.dataframe(history, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.warning(f"Status history could not be loaded: {exc}")
            st.info("Request records and status changes are stored in SQLite. Student views are filtered to the registered display name in this prototype; this is not production-grade access control.")

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
            student = str(row["Student Name"]).strip() or "Student"
            due = show_date(row["Expected Due Date"])
            draft = (
                f"Subject: Follow-up on {row['Request ID']}\n\n"
                f"Dear {office},\n\n"
                f"I am following up on request {row['Request ID']} "
                f"({row['Request Type']}), submitted on {show_date(row['Submission Date'])}. "
                f"The current status is {row['Status']} and the expected response date is {due}. "
                f"Could you please share an update when possible?\n\n"
                f"Thank you,\n{student}"
            )
            st.text_area("Review this message before sending", value=draft, height=220)
            st.caption("This is a simple text template. It is not sent automatically.")

elif page == "Faculty Monitoring":
    hero("Faculty monitoring", "A central view for spotting urgent requests and routing them to the appropriate review group.")
    st.warning("Teacher monitoring is available to registered Teacher accounts. This remains a local prototype, not a production deployment.")
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
        z.metric("Evidence awaiting review", int(active["Evidence Verification"].isin(["Pending Verification", "Evidence Required"]).sum()) if not active.empty else 0)
        route = st.selectbox("Route by category", ["All categories", "OD Monitoring", "Certificates / Admin", "General Requests"])
        view = active if route == "All categories" or active.empty else active[active["Routing Group"] == route]
        if view.empty:
            st.success("No unresolved requests in this category.")
        else:
            st.dataframe(view[["Request ID", "Student Name", "Request Type", "Activity Name", "Activity Date", "Activity Time", "Evidence File Name", "Evidence Verification", "Status", "Priority", "Routing Group"]], use_container_width=True, hide_index=True)
            st.subheader("Review a request")
            chosen = st.selectbox("Select request", view["Request ID"].astype(str).tolist(), key="faculty_review_id")
            row = view[view["Request ID"].astype(str) == chosen].iloc[0]
            st.write(f"**Student:** {row['Student Name'] or 'Not entered'}")
            st.write(f"**Request:** {row['Request Type']} — {row['Activity Name'] or row['Request Type']}")
            st.write(f"**Priority reason:** {row['Priority reason']}")
            st.write(f"**Evidence filename:** {row['Evidence File Name'] or 'No filename recorded'}")
            st.write(f"**Evidence verification:** {row['Evidence Verification'] or 'Evidence Required'}")
            st.write("Evidence must be reviewed manually; the system does not automatically analyse documents or verify authenticity. Secure faculty authentication, a private evidence viewer, and automatic notifications are not implemented. Faculty must make the actual decision.")
            st.subheader("Faculty action")
            st.caption("Accept a request, move it through review, or mark it completed. Every status change is added to the request tracking timeline.")
            allowed_next = [status for status in STATUSES if status != str(row["Status"])]
            with st.form(f"faculty_action_{chosen}"):
                action_status = st.selectbox(
                    "Update request status",
                    allowed_next,
                    index=allowed_next.index("Accepted") if "Accepted" in allowed_next else 0,
                    key=f"faculty_status_{chosen}",
                )
                action_owner = st.text_input(
                    "Assigned faculty / office",
                    value=str(row.get("Assigned To", "") or st.session_state.get("display_name", "")),
                    key=f"faculty_owner_{chosen}",
                )
                action_note = st.text_area(
                    "Update note for the student tracking timeline",
                    value="",
                    placeholder="e.g. Request accepted; processing will begin.",
                    key=f"faculty_note_{chosen}",
                )
                action_submit = st.form_submit_button("Save faculty action", type="primary", use_container_width=True)
            if action_submit:
                current = st.session_state.requests_df.copy()
                # pandas 3.x can infer datetime64 columns and reject Python date assignments.
                # Keep editable date columns as object so date.today() remains compatible.
                for date_col in ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]:
                    if date_col in current.columns:
                        current[date_col] = current[date_col].astype(object)
                idxs = current.index[current["Request ID"].astype(str) == str(chosen)]
                if len(idxs) == 0:
                    st.error("This request could not be found. Refresh and try again.")
                else:
                    idx = idxs[0]
                    current.loc[idx, "Status"] = action_status
                    current.loc[idx, "Assigned To"] = action_owner.strip()
                    current.loc[idx, "Last Updated"] = date.today()
                    current.loc[idx, "Faculty Notes"] = action_note.strip() or str(current.loc[idx, "Faculty Notes"] or "")
                    if action_status in {"Completed", "Rejected"}:
                        current.loc[idx, "College Response Date"] = date.today()
                    st.session_state.requests_df = current
                    save_data(current, note=action_note.strip() or f"Faculty updated status to {action_status}")
                    st.success(f"{chosen} updated to {action_status}. The tracking timeline has been recorded.")
                    st.rerun()
            st.info("Review permissions are prototype-level; validate them thoroughly before real deployment.")

elif page == "Manage Requests":
    hero("Manage requests", "Edit entries, delete test data, or import and export CSV files.")
    df = st.session_state.requests_df
    if df.empty:
        st.info("There are no requests yet. Add one or import a CSV file.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.subheader("Edit a request")
        ids = df["Request ID"].astype(str).tolist()
        selected = st.selectbox("Select request", ids, key="edit_id")
        row = df[df["Request ID"].astype(str) == selected].iloc[0]
        with st.form("edit_form"):
            a, b = st.columns(2)
            with a:
                req_type = st.text_input("Request type", value=str(row["Request Type"]))
                submitted_date = st.date_input("Submission date", value=to_date(row["Submission Date"]) or date.today(), key="ed_sub")
                due_date = st.date_input("Expected due date", value=to_date(row["Expected Due Date"]) or date.today(), key="ed_due")
                old_status = str(row["Status"])
                status = st.selectbox("Status", STATUSES, index=STATUSES.index(old_status) if old_status in STATUSES else 0)
            with b:
                owner = st.text_input("Assigned staff / office", value=str(row["Assigned To"]))

                # Ensure Streamlit receives a datetime.date, never NaN/float.
                updated_value = to_date(row["Last Updated"])
                if not isinstance(updated_value, date):
                    updated_value = date.today()

                updated = st.date_input(
                    "Last updated date",
                    value=updated_value,
                    key="ed_upd",
                )
                notes = st.text_area("Notes", value=str(row["Notes"]), height=130)

            update = st.form_submit_button("Save changes", type="primary", use_container_width=True)
        if update:
            if not req_type.strip():
                st.error("Request type cannot be empty.")
            elif due_date < submitted_date or updated < submitted_date:
                st.error("Due date and last-updated date must not be earlier than the submission date.")
            else:
                current = st.session_state.requests_df.copy()
                # Keep date columns object-typed before assigning datetime.date values (pandas 3.x).
                for date_col in ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]:
                    if date_col in current.columns:
                        current[date_col] = current[date_col].astype(object)
                idx = current.index[current["Request ID"].astype(str) == selected][0]
                for col, val in {"Request Type": req_type.strip(), "Submission Date": submitted_date,
                                 "Expected Due Date": due_date, "Status": status, "Assigned To": owner.strip(),
                                 "Last Updated": updated, "Notes": notes.strip()}.items():
                    current.loc[idx, col] = val
                st.session_state.requests_df = current
                save_data(current)
                st.success("Request updated.")
                st.rerun()
        st.subheader("Evidence and faculty review")
        with st.form("review_fields_form"):
            ev_current = str(row.get("Evidence Verification", "Evidence Required"))
            ev_index = EVIDENCE_STATUSES.index(ev_current) if ev_current in EVIDENCE_STATUSES else 0
            evidence_status = st.selectbox("Evidence verification status", EVIDENCE_STATUSES, index=ev_index)
            faculty_notes = st.text_area("Faculty / review notes", value=str(row.get("Faculty Notes", "")))
            review_save = st.form_submit_button("Save review details", type="primary")
        if review_save:
            current = st.session_state.requests_df.copy()
            # Keep date columns object-typed before assigning datetime.date values (pandas 3.x).
            for date_col in ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]:
                if date_col in current.columns:
                    current[date_col] = current[date_col].astype(object)
            idx = current.index[current["Request ID"].astype(str) == selected][0]
            current.loc[idx, "Evidence Verification"] = evidence_status
            current.loc[idx, "Faculty Notes"] = faculty_notes.strip()
            if str(current.loc[idx, "Status"]) in {"Completed", "Rejected"}:
                current.loc[idx, "College Response Date"] = date.today()
            st.session_state.requests_df = current
            save_data(current)
            st.success("Evidence/review details saved.")
            st.rerun()

        st.subheader("Delete a request")
        confirm = st.checkbox(f"I want to permanently delete {selected}", key="confirm_delete")
        if st.button("Delete selected request", disabled=not confirm):
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
                date_columns = ["Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"]
                for c in date_columns:
                    incoming[c] = pd.to_datetime(incoming[c], errors="coerce").dt.date
                for c in COLUMNS:
                    if c not in date_columns:
                        incoming[c] = incoming[c].fillna("").astype(str)
                # Duplicate or blank IDs make tracking/editing ambiguous.
                if incoming["Request ID"].str.strip().eq("").any() or incoming["Request ID"].duplicated().any():
                    st.warning("Blank or duplicate request IDs were found. They will be regenerated during import.")
                st.caption(f"{len(incoming)} row(s) found.")
                if st.button("Import CSV", type="primary"):
                    if method == "Replace current requests":
                        result = blank_data()
                        for _, incoming_row in incoming.iterrows():
                            item = incoming_row.to_dict()
                            if not str(item["Request ID"]).strip() or str(item["Request ID"]) in set(result["Request ID"].astype(str)):
                                item["Request ID"] = next_id(result)
                            result = pd.concat([result, pd.DataFrame([item])], ignore_index=True)
                    else:
                        result = st.session_state.requests_df.copy()
                        for _, incoming_row in incoming.iterrows():
                            item = incoming_row.to_dict()
                            if not str(item["Request ID"]).strip() or str(item["Request ID"]) in set(result["Request ID"].astype(str)):
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
### Project overview
EchoGuard AI is a student-built prototype intended to make college request progress easier to record, monitor, and discuss. It highlights possible delay signals so users can decide which requests may need attention.

### Pages and included features
- **Dashboard:** overview of request records and their statuses.
- **Add Request:** record request type, dates, activity details, notes, and evidence status.
- **Request Tracking:** find requests, apply filters, and review individual request details.
- **Delay Analysis:** view rule-based warning signs, an experimental delay indicator, and suggested next actions.
- **Faculty Monitoring:** review requests using category-based routing and monitoring information.
- **Manage Requests:** maintain records and import/export CSV data.
- **About:** project purpose, scope, limitations, and data-handling information.

### Technology and data flow
- **Language:** Python
- **Interface:** Streamlit with custom CSS
- **Data handling:** pandas
- **Storage:** SQLite database (`echoguard.db`) managed by `echoguard_backend.py`
- **Legacy migration:** existing `echoguard_requests.csv` records are imported on first run only when the database is empty. CSV import/export remains available from Manage Requests.

### How to run
Install the required packages with `pip install streamlit pandas`, open a terminal in the project folder, and run `streamlit run app.py`.

### What makes the prototype useful
It keeps request details and evidence status together, routes request categories for monitoring, highlights potential time/delay issues, and prepares follow-up message drafts for a person to review.

### Important limitations
The delay percentage is **not a validated probability** and is based on hand-written rules, not a trained or validated AI model. The teacher view uses local account authentication and role-specific navigation, but still needs a security review. Uploaded evidence files are stored locally through the backend helper, but there is no authenticated/private evidence viewer or production-grade access control. Automatic document analysis is not connected. Evidence must be reviewed manually; follow-up drafts are simple text templates, not messages sent automatically. Production deployment requires security review and end-to-end testing.

### Privacy and demo guidance
Request data is stored locally in SQLite (`echoguard.db`) and evidence uploads are stored in a local `evidence_uploads` folder. This is not a secure multi-user deployment. Use fictional records for the hackathon demonstration and do not enter sensitive student information.
""")

st.divider()
st.caption("EchoGuard AI · Student prototype · Review suggested actions before acting on them.")
