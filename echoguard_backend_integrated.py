"""EchoGuard AI backend: SQLite persistence and request-management helpers.

This module uses the same column names as echoguard_app_role_based.py.
It is a local prototype backend, not a production authentication service.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "echoguard.db"
EVIDENCE_DIR = BASE_DIR / "evidence_uploads"
COLUMNS = [
    "Request ID", "Request Type", "Submission Date", "Expected Due Date",
    "Status", "Assigned To", "Last Updated", "Notes", "Student Name",
    "Activity Name", "Activity Date", "Activity Time", "Evidence File Name",
    "Evidence Verification", "Routing Group", "Faculty Notes", "College Response Date",
]
DATE_COLUMNS = {"Submission Date", "Expected Due Date", "Last Updated", "Activity Date", "College Response Date"}
STATUSES = {"Submitted", "Under Review", "Waiting for Information", "In Progress", "Accepted", "Completed", "Rejected"}
EVIDENCE_STATUSES = {"Evidence Required", "Pending Verification", "AI Review", "Verified", "Verification Issue", "Not Required"}


class BackendError(Exception):
    """Expected validation or persistence error suitable for showing to a user."""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def initialize_database() -> None:
    """Create the request table and useful indexes if they do not exist."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY,
                request_type TEXT NOT NULL,
                submission_date TEXT NOT NULL,
                expected_due_date TEXT,
                status TEXT NOT NULL,
                assigned_to TEXT NOT NULL DEFAULT '',
                last_updated TEXT,
                notes TEXT NOT NULL DEFAULT '',
                student_name TEXT NOT NULL DEFAULT '',
                activity_name TEXT NOT NULL DEFAULT '',
                activity_date TEXT,
                activity_time TEXT NOT NULL DEFAULT '',
                evidence_file_name TEXT NOT NULL DEFAULT '',
                evidence_verification TEXT NOT NULL DEFAULT 'Not Required',
                routing_group TEXT NOT NULL DEFAULT '',
                faculty_notes TEXT NOT NULL DEFAULT '',
                college_response_date TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Upgrade older EchoGuard databases in place. CREATE TABLE IF NOT EXISTS does
        # not add columns to an existing table, which caused "no such column: status"
        # when users had an earlier schema. Add missing columns without deleting rows.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(requests)").fetchall()}
        migrations = {
            "request_id": "TEXT",
            "request_type": "TEXT NOT NULL DEFAULT ''",
            "submission_date": "TEXT NOT NULL DEFAULT ''",
            "expected_due_date": "TEXT",
            "status": "TEXT NOT NULL DEFAULT 'Submitted'",
            "assigned_to": "TEXT NOT NULL DEFAULT ''",
            "last_updated": "TEXT",
            "notes": "TEXT NOT NULL DEFAULT ''",
            "student_name": "TEXT NOT NULL DEFAULT ''",
            "activity_name": "TEXT NOT NULL DEFAULT ''",
            "activity_date": "TEXT",
            "activity_time": "TEXT NOT NULL DEFAULT ''",
            "evidence_file_name": "TEXT NOT NULL DEFAULT ''",
            "evidence_verification": "TEXT NOT NULL DEFAULT 'Not Required'",
            "routing_group": "TEXT NOT NULL DEFAULT ''",
            "faculty_notes": "TEXT NOT NULL DEFAULT ''",
            "college_response_date": "TEXT",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }
        for column, declaration in migrations.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE requests ADD COLUMN {column} {declaration}")
        # Give older rows stable IDs when the previous schema did not have request_id.
        conn.execute("UPDATE requests SET request_id = 'EG-' || printf('%04d', rowid) WHERE request_id IS NULL OR TRIM(request_id) = ''")
        conn.execute("UPDATE requests SET status = 'Submitted' WHERE status IS NULL OR TRIM(status) = ''")
        conn.execute("UPDATE requests SET request_type = 'General' WHERE request_type IS NULL OR TRIM(request_type) = ''")
        conn.execute("UPDATE requests SET submission_date = date('now') WHERE submission_date IS NULL OR TRIM(submission_date) = ''")
        conn.execute("UPDATE requests SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL OR TRIM(created_at) = ''")
        conn.execute("UPDATE requests SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL OR TRIM(updated_at) = ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_student ON requests(student_name)")


def _text(value: Any) -> str:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def _normalise(record: Mapping[str, Any], *, require_id: bool = True) -> dict[str, str]:
    item = {c: _text(record.get(c, "")) for c in COLUMNS}
    if require_id and not item["Request ID"]:
        raise BackendError("Request ID is required.")
    if not item["Request Type"]:
        raise BackendError("Request type cannot be empty.")
    if not item["Submission Date"]:
        item["Submission Date"] = date.today().isoformat()
    for col in DATE_COLUMNS:
        if item[col]:
            try:
                item[col] = pd.to_datetime(item[col], errors="raise").date().isoformat()
            except Exception as exc:
                raise BackendError(f"Invalid date in '{col}'. Use YYYY-MM-DD.") from exc
    if item["Expected Due Date"] and item["Expected Due Date"] < item["Submission Date"]:
        raise BackendError("Expected due date cannot be earlier than submission date.")
    if item["Last Updated"] and item["Last Updated"] < item["Submission Date"]:
        raise BackendError("Last updated date cannot be earlier than submission date.")
    if item["Status"] not in STATUSES:
        raise BackendError("Invalid request status.")
    if item["Evidence Verification"] and item["Evidence Verification"] not in EVIDENCE_STATUSES:
        raise BackendError("Invalid evidence verification status.")
    return item


def _db_row_to_record(row: sqlite3.Row) -> dict[str, str]:
    return {
        "Request ID": row["request_id"], "Request Type": row["request_type"],
        "Submission Date": row["submission_date"] or "", "Expected Due Date": row["expected_due_date"] or "",
        "Status": row["status"], "Assigned To": row["assigned_to"] or "", "Last Updated": row["last_updated"] or "",
        "Notes": row["notes"] or "", "Student Name": row["student_name"] or "", "Activity Name": row["activity_name"] or "",
        "Activity Date": row["activity_date"] or "", "Activity Time": row["activity_time"] or "",
        "Evidence File Name": row["evidence_file_name"] or "", "Evidence Verification": row["evidence_verification"] or "Not Required",
        "Routing Group": row["routing_group"] or "", "Faculty Notes": row["faculty_notes"] or "",
        "College Response Date": row["college_response_date"] or "",
    }


def list_requests() -> pd.DataFrame:
    initialize_database()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM requests ORDER BY created_at, request_id").fetchall()
    records = [_db_row_to_record(r) for r in rows]
    return pd.DataFrame(records, columns=COLUMNS)


def get_request(request_id: str) -> dict[str, str] | None:
    initialize_database()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM requests WHERE request_id = ?", (str(request_id),)).fetchone()
    return _db_row_to_record(row) if row else None


def create_request(record: Mapping[str, Any]) -> str:
    item = _normalise(record)
    initialize_database()
    keys = ["request_id", "request_type", "submission_date", "expected_due_date", "status", "assigned_to", "last_updated", "notes", "student_name", "activity_name", "activity_date", "activity_time", "evidence_file_name", "evidence_verification", "routing_group", "faculty_notes", "college_response_date"]
    values = [item[c] for c in COLUMNS]
    with _connect() as conn:
        try:
            conn.execute(f"INSERT INTO requests ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})", values)
        except sqlite3.IntegrityError as exc:
            raise BackendError(f"Request ID '{item['Request ID']}' already exists.") from exc
    return item["Request ID"]


def update_request(request_id: str, changes: Mapping[str, Any]) -> None:
    existing = get_request(request_id)
    if existing is None:
        raise BackendError(f"Request '{request_id}' was not found.")
    merged = {**existing, **dict(changes), "Request ID": str(request_id)}
    item = _normalise(merged)
    db_columns = ["request_type", "submission_date", "expected_due_date", "status", "assigned_to", "last_updated", "notes", "student_name", "activity_name", "activity_date", "activity_time", "evidence_file_name", "evidence_verification", "routing_group", "faculty_notes", "college_response_date"]
    values = [item[c] for c in COLUMNS[1:]] + [datetime.now().isoformat(timespec="seconds"), str(request_id)]
    assignments = ", ".join(f"{col} = ?" for col in db_columns) + ", updated_at = ?"
    with _connect() as conn:
        cur = conn.execute(f"UPDATE requests SET {assignments} WHERE request_id = ?", values)
        if cur.rowcount == 0:
            raise BackendError(f"Request '{request_id}' was not found.")


def delete_request(request_id: str) -> bool:
    initialize_database()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM requests WHERE request_id = ?", (str(request_id),))
    return cur.rowcount > 0


def save_requests(frame: pd.DataFrame) -> None:
    """Compatibility adapter for the current Streamlit frontend's DataFrame workflow.

    The full set is validated before a transaction replaces SQLite records, so invalid
    data does not partially overwrite the database. Prefer CRUD functions for new code.
    """
    if frame is None:
        raise BackendError("No request data was provided.")
    work = frame.copy()
    for col in COLUMNS:
        if col not in work.columns:
            work[col] = ""
    work = work[COLUMNS].fillna("")
    records = [_normalise(row, require_id=True) for row in work.to_dict(orient="records")]
    ids = [r["Request ID"] for r in records]
    if len(ids) != len(set(ids)):
        raise BackendError("Duplicate Request IDs found; no data was saved.")
    initialize_database()
    db_cols = ["request_id", "request_type", "submission_date", "expected_due_date", "status", "assigned_to", "last_updated", "notes", "student_name", "activity_name", "activity_date", "activity_time", "evidence_file_name", "evidence_verification", "routing_group", "faculty_notes", "college_response_date"]
    sql = f"INSERT INTO requests ({', '.join(db_cols)}) VALUES ({', '.join('?' for _ in db_cols)})"
    values = [[r[c] for c in COLUMNS] for r in records]
    with _connect() as conn:
        conn.execute("DELETE FROM requests")
        if values:
            conn.executemany(sql, values)


def load_requests() -> pd.DataFrame:
    """DataFrame loader for the current Streamlit frontend."""
    return list_requests()


def migrate_csv_once(csv_path: str | Path) -> int:
    """Import legacy frontend CSV only when SQLite is empty; never overwrite DB rows."""
    csv_path = Path(csv_path)
    initialize_database()
    if not csv_path.exists():
        return 0
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    if count:
        return 0
    try:
        frame = pd.read_csv(csv_path, dtype={"Request ID": str}).fillna("")
    except Exception as exc:
        raise BackendError(f"Could not read legacy CSV; database was not changed: {exc}") from exc
    if frame.empty:
        return 0
    for col in COLUMNS:
        if col not in frame:
            frame[col] = ""
    frame = frame[COLUMNS]
    # Older CSVs may omit status; provide a safe default before validation.
    frame["Status"] = frame["Status"].replace("", "Submitted")
    frame["Evidence Verification"] = frame["Evidence Verification"].replace("", "Not Required")
    # Regenerate blank or duplicate IDs without changing valid unique IDs.
    used = set()
    next_num = 1
    for i, rid in frame["Request ID"].astype(str).items():
        rid = rid.strip()
        if not rid or rid in used:
            while f"EG-{next_num:04d}" in used:
                next_num += 1
            rid = f"EG-{next_num:04d}"
            next_num += 1
        frame.at[i, "Request ID"] = rid
        used.add(rid)
    save_requests(frame)
    return len(frame)


def save_evidence(uploaded_file: Any, request_id: str) -> str:
    """Store a Streamlit UploadedFile safely and return the saved basename.

    Only PDF/PNG/JPG/JPEG are accepted; this saves bytes but does not inspect document
    authenticity or run AI verification.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(request_id)):
        raise BackendError("Invalid request ID for evidence storage.")
    original_name = Path(str(getattr(uploaded_file, "name", "evidence"))).name
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise BackendError("Evidence must be PDF, PNG, JPG, or JPEG.")
    data = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else bytes(uploaded_file)
    if not data:
        raise BackendError("The uploaded evidence file is empty.")
    if len(data) > 10 * 1024 * 1024:
        raise BackendError("Evidence files must be 10 MB or smaller.")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{request_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}{suffix}"
    destination = EVIDENCE_DIR / safe_name
    destination.write_bytes(data)
    return safe_name


def export_csv() -> bytes:
    """Export stored requests in the same column format as the frontend CSV."""
    frame = list_requests()
    for col in DATE_COLUMNS:
        frame[col] = pd.to_datetime(frame[col], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    return frame.to_csv(index=False).encode("utf-8-sig")


def import_csv(file_bytes: bytes, *, replace: bool = False) -> int:
    """Validate and import CSV rows. Add mode skips existing IDs; replace mode replaces all."""
    try:
        frame = pd.read_csv(io.BytesIO(file_bytes), dtype={"Request ID": str}).fillna("")
    except Exception as exc:
        raise BackendError(f"Could not read the uploaded CSV: {exc}") from exc
    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        raise BackendError("CSV is missing required columns: " + ", ".join(missing))
    records = [_normalise(r) for r in frame[COLUMNS].to_dict(orient="records")]
    ids = [r["Request ID"] for r in records]
    if len(ids) != len(set(ids)):
        raise BackendError("The imported CSV contains duplicate Request IDs.")
    initialize_database()
    with _connect() as conn:
        if replace:
            conn.execute("DELETE FROM requests")
        existing = {r[0] for r in conn.execute("SELECT request_id FROM requests")}
        insert_cols = ["request_id", "request_type", "submission_date", "expected_due_date", "status", "assigned_to", "last_updated", "notes", "student_name", "activity_name", "activity_date", "activity_time", "evidence_file_name", "evidence_verification", "routing_group", "faculty_notes", "college_response_date"]
        sql = f"INSERT INTO requests ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})"
        added = 0
        for r in records:
            if r["Request ID"] in existing:
                if replace:
                    raise BackendError("Duplicate Request IDs found in the import file.")
                continue
            conn.execute(sql, [r[c] for c in COLUMNS])
            existing.add(r["Request ID"])
            added += 1
    return added


initialize_database()
