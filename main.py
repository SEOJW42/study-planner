from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
from datetime import datetime

app = FastAPI()

# 데이터 모델
class StudyRecord(BaseModel):
    subject: str
    study_date: str
    duration_minutes: int
    is_completed: bool

# DB 초기화
def init_db():
    conn = sqlite3.connect("planner.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            study_date TEXT,
            duration_minutes INTEGER,
            is_completed BOOLEAN
        )
    """)
    conn.commit()
    conn.close()

init_db()

# API 엔드포인트: 기록 저장
@app.post("/api/records/")
async def save_record(record: StudyRecord):
    conn = sqlite3.connect("planner.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO records (subject, study_date, duration_minutes, is_completed) VALUES (?, ?, ?, ?)",
        (record.subject, record.study_date, record.duration_minutes, record.is_completed)
    )
    conn.commit()
    conn.close()
    return {"message": "success"}

# API 엔드포인트: 잔디 심기(Heatmap)용 데이터 불러오기
@app.get("/api/heatmap/")
async def get_heatmap():
    conn = sqlite3.connect("planner.db")
    cursor = conn.cursor()
    # 날짜별로 총 학습 시간을 합산
    cursor.execute("SELECT study_date, SUM(duration_minutes) FROM records GROUP BY study_date")
    rows = cursor.fetchall()
    conn.close()
    
    heatmap_data = []
    for row in rows:
        # Cal-Heatmap v4 형식에 맞게 리턴 [{"date": "YYYY-MM-DD", "value": 분}]
        heatmap_data.append({"date": row[0], "value": row[1]})
    
    return heatmap_data

# 프론트엔드 파일(HTML, JS 등)을 서빙하는 설정 (가장 마지막에 위치해야 함)
app.mount("/", StaticFiles(directory="static", html=True), name="static")