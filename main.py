import os
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

app = FastAPI()
DATABASE_URL = os.getenv("DATABASE_URL")

# --- 데이터 모델 ---
class RoutineCreate(BaseModel):
    subject: str
    target_minutes: int
    repeat_days: str  # 예: "0,1,2,3,4,5,6" (0=일요일)

class SyncTask(BaseModel):
    date: str
    routine_id: int = None
    subject: str
    target_minutes: int
    duration_minutes: int
    is_completed: bool

class TaskEdit(BaseModel):
    subject: str
    target_minutes: int
    repeat_days: str

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # 일일 기록 테이블 (routine_id 추가)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id SERIAL PRIMARY KEY,
            subject VARCHAR(255),
            study_date DATE,
            duration_minutes INTEGER DEFAULT 0,
            is_completed BOOLEAN DEFAULT FALSE,
            target_minutes INTEGER DEFAULT 0,
            routine_id INTEGER
        )
    """)
    # 반복 요일(루틴) 테이블 생성
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS routines (
            id SERIAL PRIMARY KEY,
            subject VARCHAR(255),
            target_minutes INTEGER DEFAULT 0,
            repeat_days VARCHAR(20)
        )
    """)
    # 기존 테이블 호환성 유지용
    try: cursor.execute("ALTER TABLE records ADD COLUMN IF NOT EXISTS routine_id INTEGER")
    except: pass
    
    conn.commit()
    cursor.close()
    conn.close()

init_db()

# 1. 특정 날짜의 과목(루틴 + 당일 기록) 불러오기
@app.get("/api/tasks/{query_date}")
async def get_tasks(query_date: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    dt = datetime.strptime(query_date, "%Y-%m-%d")
    js_day = str(dt.strftime("%w")) # 0=일요일, 6=토요일

    # 해당 날짜의 실제 학습 기록
    cursor.execute("SELECT * FROM records WHERE study_date = %s ORDER BY id ASC", (query_date,))
    records = cursor.fetchall()

    # 해당 요일에 해당하는 루틴(목표)
    cursor.execute("SELECT * FROM routines WHERE repeat_days LIKE %s", ('%' + js_day + '%',))
    routines = cursor.fetchall()
    
    cursor.close()
    conn.close()

    tasks = []
    record_routine_ids = set()
    
    # 1) 이미 타이머가 돌아간(기록된) 과목들
    for r in records:
        tasks.append({
            "uuid": f"record_{r['id']}",
            "type": "record",
            "id": r["id"],
            "subject": r["subject"],
            "target_minutes": r["target_minutes"],
            "duration_minutes": r["duration_minutes"],
            "is_completed": r["is_completed"],
            "routine_id": r["routine_id"],
            "repeat_days": "" 
        })
        if r["routine_id"]:
            record_routine_ids.add(r["routine_id"])

    # 2) 오늘 해야 할 루틴이지만 아직 타이머를 안 켠 과목들 병합
    routine_dict = {rt["id"]: rt["repeat_days"] for rt in routines}
    for rt in routines:
        if rt["id"] not in record_routine_ids:
            tasks.append({
                "uuid": f"routine_{rt['id']}",
                "type": "routine",
                "id": rt["id"],
                "subject": rt["subject"],
                "target_minutes": rt["target_minutes"],
                "duration_minutes": 0,
                "is_completed": False,
                "routine_id": rt["id"],
                "repeat_days": rt["repeat_days"]
            })

    # 기록된 과목에도 요일 정보(수정 시 필요) 채워넣기
    for t in tasks:
        if t["routine_id"] and t["routine_id"] in routine_dict:
            t["repeat_days"] = routine_dict[t["routine_id"]]

    return tasks

# 2. 새로운 요일 반복 과목 추가
@app.post("/api/routines/")
async def create_routine(data: RoutineCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO routines (subject, target_minutes, repeat_days) VALUES (%s, %s, %s) RETURNING id",
        (data.subject, data.target_minutes, data.repeat_days)
    )
    new_id = cursor.fetchone()['id']
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success"}

# 3. 타이머 자동 동기화 (기록이 없으면 생성, 있으면 수정)
@app.post("/api/records/sync")
async def sync_record(data: SyncTask):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if data.routine_id:
        cursor.execute("SELECT id FROM records WHERE study_date = %s AND routine_id = %s", (data.date, data.routine_id))
    else:
        cursor.execute("SELECT id FROM records WHERE study_date = %s AND subject = %s", (data.date, data.subject))
        
    row = cursor.fetchone()
    if row: # 업데이트
        cursor.execute(
            "UPDATE records SET duration_minutes = %s, is_completed = %s WHERE id = %s RETURNING id",
            (data.duration_minutes, data.is_completed, row['id'])
        )
    else: # 새로 저장
        cursor.execute(
            "INSERT INTO records (subject, study_date, duration_minutes, is_completed, target_minutes, routine_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (data.subject, data.date, data.duration_minutes, data.is_completed, data.target_minutes, data.routine_id)
        )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success"}

# 4. 수정 및 삭제
@app.put("/api/tasks/{task_type}/{task_id}/edit")
async def edit_task(task_type: str, task_id: int, data: TaskEdit):
    conn = get_db_connection()
    cursor = conn.cursor()
    if task_type == 'routine' or data.repeat_days:
        r_id = task_id if task_type == 'routine' else cursor.execute("SELECT routine_id FROM records WHERE id=%s", (task_id,)).fetchone()['routine_id']
        cursor.execute("UPDATE routines SET subject = %s, target_minutes = %s, repeat_days = %s WHERE id = %s", (data.subject, data.target_minutes, data.repeat_days, r_id))
        cursor.execute("UPDATE records SET subject = %s, target_minutes = %s WHERE routine_id = %s", (data.subject, data.target_minutes, r_id))
    else:
        cursor.execute("UPDATE records SET subject = %s, target_minutes = %s WHERE id = %s", (data.subject, data.target_minutes, task_id))
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success"}

@app.delete("/api/tasks/{task_type}/{task_id}")
async def delete_task(task_type: str, task_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    if task_type == 'routine':
        cursor.execute("DELETE FROM routines WHERE id = %s", (task_id,))
    else:
        cursor.execute("DELETE FROM records WHERE id = %s", (task_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "deleted"}

# 5. 캘린더용 데이터 불러오기 (기존과 동일)
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