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

class RecordUpdate(BaseModel):
    duration_minutes: int
    is_completed: bool

# DB 연결 함수 (결과를 딕셔너리로 받기 위해 RealDictCursor 사용)
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
            is_completed BOOLEAN DEFAULT FALSE
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

init_db()

# 1. 오늘 날짜의 과목 목록 불러오기
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

# 2. 새로운 과목 등록하기
@app.post("/api/records/")
async def create_record(record: SubjectCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    today_str = date.today().isoformat()
    cursor.execute(
        "INSERT INTO records (subject, study_date, duration_minutes, is_completed) VALUES (%s, %s, 0, FALSE) RETURNING id",
        (record.subject, today_str)
    )
    new_id = cursor.fetchone()['id']
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success", "id": new_id}

# 3. 타이머 시간 및 완료 상태 업데이트
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

# 4. 잔디 심기용 데이터
@app.get("/api/heatmap/")
async def get_heatmap():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TO_CHAR(study_date, 'YYYY-MM-DD') as date, SUM(duration_minutes) as total FROM records GROUP BY study_date")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return [{"date": row['date'], "value": row['total']} for row in rows]

# 5. 캘린더 특정 날짜 클릭 시 상세 기록 보기
@app.get("/api/records/date/{query_date}")
async def get_daily_records(query_date: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subject, duration_minutes, is_completed FROM records WHERE study_date = %s", (query_date,))
    records = cursor.fetchall()
    cursor.close()
    conn.close()
    return records

app.mount("/", StaticFiles(directory="static", html=True), name="static")