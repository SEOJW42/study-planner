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

# --- 데이터 모델 (목표 시간 추가) ---
class SubjectCreate(BaseModel):
    subject: str
    target_minutes: int

class RecordUpdate(BaseModel):
    duration_minutes: int
    is_completed: bool

# DB 연결 함수
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# DB 초기화 및 업데이트 (목표 시간 컬럼 자동 추가)
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id SERIAL PRIMARY KEY,
            subject VARCHAR(255),
            study_date DATE,
            duration_minutes INTEGER DEFAULT 0,
            is_completed BOOLEAN DEFAULT FALSE
        )
    """)
    conn.commit()
    
    # 새로운 '목표 시간' 컬럼이 없다면 안전하게 추가합니다.
    try:
        cursor.execute("ALTER TABLE records ADD COLUMN IF NOT EXISTS target_minutes INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        conn.rollback()

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
    # 목표 시간도 함께 저장
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

# 캘린더 데이터 조회 (총 학습 시간과 총 목표 시간 반환)
@app.get("/api/heatmap/")
async def get_heatmap():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TO_CHAR(study_date, 'YYYY-MM-DD') as date, SUM(duration_minutes) as total, SUM(target_minutes) as target FROM records GROUP BY study_date")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return [{"date": row['date'], "value": row['total'], "target": row['target']} for row in rows]

# 상세 기록 조회 (목표 시간 포함)
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