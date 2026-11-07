import os
import sqlite3

# Overridable so tests can point at a throwaway database
DB_PATH = os.environ.get("BGV_DB_PATH", "data/bgv.db")

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    return sqlite3.connect(DB_PATH)

def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
        candidate_id TEXT PRIMARY KEY,
        name TEXT,
        email TEXT,
        phone TEXT,
        status TEXT DEFAULT 'Pending'
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id TEXT,
        document_type TEXT,
        file_name TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_name TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_candidates INTEGER DEFAULT 0,
        completed INTEGER DEFAULT 0,
        partial INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS batch_candidates (
        batch_id INTEGER,
        candidate_id TEXT,
        FOREIGN KEY (batch_id) REFERENCES batches(id)
    )
    """)

    # One row per field read from a document. status: ok / invalid / dropped / missing.
    # Aadhaar numbers are stored masked (XXXX XXXX 1234), never in full.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS extracted_fields (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id INTEGER,
        candidate_id TEXT,
        document_type TEXT,
        field TEXT,
        value TEXT,
        status TEXT,
        source TEXT,
        note TEXT,
        FOREIGN KEY (document_id) REFERENCES documents(id)
    )
    """)

    # Older databases were created before documents had uploaded_at.
    # SQLite refuses a CURRENT_TIMESTAMP default when adding a column to a
    # non-empty table, so add it plain; insert_document sets it explicitly.
    # classified_by / confidence record whether the LLM or the keyword rules labelled the document.
    columns = [row[1] for row in cursor.execute("PRAGMA table_info(documents)")]
    for column, sql_type in [("uploaded_at", "TIMESTAMP"), ("classified_by", "TEXT"), ("confidence", "REAL")]:
        if column not in columns:
            cursor.execute(f"ALTER TABLE documents ADD COLUMN {column} {sql_type}")

    conn.commit()
    conn.close()

def insert_candidate(candidate_id, name, email, phone):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO candidates (candidate_id, name, email, phone)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(candidate_id) DO UPDATE SET
        name  = excluded.name,
        email = excluded.email,
        phone = excluded.phone
    """, (candidate_id, name, email, phone))

    conn.commit()
    conn.close()


def get_all_candidates():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM candidates")

    data = cursor.fetchall()

    conn.close()

    return data

def update_candidate_status(candidate_id, status):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE candidates
    SET status = ?
    WHERE candidate_id = ?
    """, (status, candidate_id))

    conn.commit()
    conn.close()

def get_candidate_count_by_status(status):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT COUNT(*)
    FROM candidates
    WHERE status = ?
    """, (status,))

    count = cursor.fetchone()[0]

    conn.close()

    return count

def insert_document(candidate_id, document_type, file_name, classified_by=None, confidence=None):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO documents
    (candidate_id, document_type, file_name, uploaded_at, classified_by, confidence)
    VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
    """, (candidate_id, document_type, file_name, classified_by, confidence))
    document_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return document_id

def insert_extracted_fields(document_id, candidate_id, document_type, fields):
    """fields: {field: {"value", "status", "source", "note"}} as returned by the extractor."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.executemany("""
    INSERT INTO extracted_fields
    (document_id, candidate_id, document_type, field, value, status, source, note)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [(document_id, candidate_id, document_type, name, f["value"], f["status"], f["source"], f["note"])
          for name, f in fields.items()])

    conn.commit()
    conn.close()

def get_extracted_fields(candidate_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT document_type, field, value, status, source, note
    FROM extracted_fields
    WHERE candidate_id = ?
    ORDER BY document_id, id
    """, (candidate_id,))

    data = cursor.fetchall()

    conn.close()

    return data

def get_candidate_documents(candidate_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM documents
    WHERE candidate_id = ?
    """, (candidate_id,))

    data = cursor.fetchall()

    conn.close()

    return data

def get_candidate_by_email(email):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT * FROM candidates
    WHERE email = ?
    """, (email,))

    candidate = cursor.fetchone()

    conn.close()

    return candidate

def get_existing_doc_types(candidate_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT document_type
        FROM documents
        WHERE candidate_id = ?
    """, (candidate_id,))

    types = [row[0] for row in cursor.fetchall()]

    conn.close()

    return types


# Python runs this once per process (imported modules are cached), so every
# page can rely on the tables existing without re-creating them on each rerun.
create_tables()

if __name__ == "__main__":
    print("Database Created Successfully")