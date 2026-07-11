import os
import psycopg2
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# .env 파일에서 데이터베이스 주소 몰래 불러오기 (보안)
load_dotenv()

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")

# 데이터 모델
class StudyRecord(BaseModel):
    subject: str
    study_date: str
    duration_minutes: int
    is_completed: bool

# DB 연결 함수
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# DB 초기화 (PostgreSQL 문법 적용)
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id SERIAL PRIMARY KEY,
            subject VARCHAR(255),
            study_date DATE,
            duration_minutes INTEGER,
            is_completed BOOLEAN
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

init_db()

# API 엔드포인트: 기록 저장
@app.post("/api/records/")
async def save_record(record: StudyRecord):
    conn = get_db_connection()
    cursor = conn.cursor()
    # PostgreSQL은 변수 자리에 %s 를 사용합니다.
    cursor.execute(
        "INSERT INTO records (subject, study_date, duration_minutes, is_completed) VALUES (%s, %s, %s, %s)",
        (record.subject, record.study_date, record.duration_minutes, record.is_completed)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success"}

# API 엔드포인트: 잔디 심기(Heatmap) 데이터 불러오기
@app.get("/api/heatmap/")
async def get_heatmap():
    conn = get_db_connection()
    cursor = conn.cursor()
    # 날짜 형식을 텍스트로 깔끔하게 가져오기 위해 TO_CHAR 사용
    cursor.execute("SELECT TO_CHAR(study_date, 'YYYY-MM-DD'), SUM(duration_minutes) FROM records GROUP BY study_date")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    heatmap_data = []
    for row in rows:
        heatmap_data.append({"date": row[0], "value": row[1]})
    
    return heatmap_data

app.mount("/", StaticFiles(directory="static", html=True), name="static")