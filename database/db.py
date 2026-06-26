import sqlite3

DB_PATH = "data/bgv.db"

def get_connection():
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
        file_name TEXT
    )
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    create_tables()
    print("Database Created Successfully")

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

def insert_document(candidate_id, document_type, file_name):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO documents
    (candidate_id, document_type, file_name)
    VALUES (?, ?, ?)
    """, (candidate_id, document_type, file_name))

    conn.commit()
    conn.close()

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