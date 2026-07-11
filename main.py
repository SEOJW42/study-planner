import os
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import date

load_dotenv()

app = FastAPI()
DATABASE_URL = os.getenv("DATABASE_URL")

# --- 데이터 모델 ---
class SubjectCreate(BaseModel):
    subject: str
    target_minutes: int

class RecordUpdate(BaseModel):
    duration_minutes: int
    is_completed: bool

class RecordEdit(BaseModel):
    subject: str
    target_minutes: int

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id SERIAL PRIMARY KEY,
            subject VARCHAR(255),
            study_date DATE,
            duration_minutes INTEGER DEFAULT 0,
            is_completed BOOLEAN DEFAULT FALSE,
            target_minutes INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

init_db()

@app.get("/api/records/today")
async def get_today_records():
    conn = get_db_connection()
    cursor = conn.cursor()
    today_str = date.today().isoformat()
    cursor.execute("SELECT * FROM records WHERE study_date = %s ORDER BY id ASC", (today_str,))
    records = cursor.fetchall()
    cursor.close()
    conn.close()
    return records

@app.post("/api/records/")
async def create_record(record: SubjectCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    today_str = date.today().isoformat()
    cursor.execute(
        "INSERT INTO records (subject, study_date, duration_minutes, is_completed, target_minutes) VALUES (%s, %s, 0, FALSE, %s) RETURNING id",
        (record.subject, today_str, record.target_minutes)
    )
    new_id = cursor.fetchone()['id']
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success", "id": new_id}

@app.put("/api/records/{record_id}")
async def update_record(record_id: int, update_data: RecordUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE records SET duration_minutes = %s, is_completed = %s WHERE id = %s",
        (update_data.duration_minutes, update_data.is_completed, record_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success"}

# --- [추가] 과목명 및 목표 시간 수정 API ---
@app.put("/api/records/{record_id}/edit")
async def edit_record(record_id: int, edit_data: RecordEdit):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE records SET subject = %s, target_minutes = %s WHERE id = %s",
        (edit_data.subject, edit_data.target_minutes, record_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success"}

# --- [추가] 기록 삭제 API ---
@app.delete("/api/records/{record_id}")
async def delete_record(record_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM records WHERE id = %s", (record_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "deleted"}

@app.get("/api/heatmap/")
async def get_heatmap():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TO_CHAR(study_date, 'YYYY-MM-DD') as date, SUM(duration_minutes) as total, SUM(target_minutes) as target FROM records GROUP BY study_date")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [{"date": row['date'], "value": row['total'], "target": row['target']} for row in rows]

@app.get("/api/records/date/{query_date}")
async def get_daily_records(query_date: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subject, duration_minutes, is_completed, target_minutes FROM records WHERE study_date = %s", (query_date,))
    records = cursor.fetchall()
    cursor.close()
    conn.close()
    return records

app.mount("/", StaticFiles(directory="static", html=True), name="static")