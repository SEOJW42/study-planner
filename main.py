import os
import hashlib
import jwt
from psycopg2.extras import RealDictCursor
import psycopg2
from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import date, datetime, timedelta

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

load_dotenv()

app = FastAPI()
DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = "my_super_secret_planner_key"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

class UserAuth(BaseModel):
    username: str
    password: str
    guest_token: str = None

class GoogleAuth(BaseModel):
    credential: str
    guest_token: str = None

class RoutineCreate(BaseModel):
    subject: str
    target_minutes: int
    repeat_days: str

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

def get_db_connection(): return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS records (id SERIAL PRIMARY KEY, subject VARCHAR(255), study_date DATE, duration_minutes INTEGER DEFAULT 0, is_completed BOOLEAN DEFAULT FALSE, target_minutes INTEGER DEFAULT 0, routine_id INTEGER, owner_id VARCHAR(255) DEFAULT 'guest')")
    cursor.execute("CREATE TABLE IF NOT EXISTS routines (id SERIAL PRIMARY KEY, subject VARCHAR(255), target_minutes INTEGER DEFAULT 0, repeat_days VARCHAR(20), owner_id VARCHAR(255) DEFAULT 'guest')")
    try:
        cursor.execute("ALTER TABLE records ADD COLUMN IF NOT EXISTS owner_id VARCHAR(255) DEFAULT 'guest'")
        cursor.execute("ALTER TABLE routines ADD COLUMN IF NOT EXISTS owner_id VARCHAR(255) DEFAULT 'guest'")
    except: pass
    conn.commit()
    cursor.close()
    conn.close()

init_db()

def hash_password(password: str) -> str: return hashlib.sha256(password.encode()).hexdigest()
def create_access_token(user_id: int, username: str):
    expire = datetime.utcnow() + timedelta(days=365)
    return jwt.encode({"user_id": user_id, "username": username, "exp": expire}, SECRET_KEY, algorithm="HS256")

def get_current_owner(request: Request) -> str:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "): return "guest"
    token = auth_header.split(" ")[1]
    if token.startswith("guest_"): return token
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return f"user_{payload.get('user_id')}"
    except: return "guest"

# --- 회원가입 / 로그인 API ---
@app.post("/api/auth/google")
async def google_login(data: GoogleAuth):
    try:
        idinfo = id_token.verify_oauth2_token(data.credential, google_requests.Request(), GOOGLE_CLIENT_ID)
        email = idinfo['email']
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = %s", (email,))
        user = cursor.fetchone()
        if not user:
            cursor.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id", (email, "google_oauth_user"))
            user_id = cursor.fetchone()['id']
            new_owner_id = f"user_{user_id}"
            if data.guest_token and data.guest_token.startswith("guest_"):
                cursor.execute("UPDATE records SET owner_id = %s WHERE owner_id = %s", (new_owner_id, data.guest_token))
                cursor.execute("UPDATE routines SET owner_id = %s WHERE owner_id = %s", (new_owner_id, data.guest_token))
        else:
            user_id = user['id']
        conn.commit()
        cursor.close()
        conn.close()
        token = create_access_token(user_id, email)
        return {"message": "success", "token": token, "username": email}
    except ValueError:
        return {"error": "유효하지 않은 구글 토큰입니다."}

@app.post("/api/auth/signup")
async def signup(data: UserAuth):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s", (data.username,))
    if cursor.fetchone(): return {"error": "이미 존재하는 아이디입니다."}
    cursor.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id", (data.username, hash_password(data.password)))
    new_user_id = cursor.fetchone()['id']
    new_owner_id = f"user_{new_user_id}"
    if data.guest_token and data.guest_token.startswith("guest_"):
        cursor.execute("UPDATE records SET owner_id = %s WHERE owner_id = %s", (new_owner_id, data.guest_token))
        cursor.execute("UPDATE routines SET owner_id = %s WHERE owner_id = %s", (new_owner_id, data.guest_token))
    conn.commit()
    cursor.close()
    conn.close()
    token = create_access_token(new_user_id, data.username)
    return {"message": "success", "token": token, "username": data.username}

@app.post("/api/auth/login")
async def login(data: UserAuth):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password_hash FROM users WHERE username = %s", (data.username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    if not user or user['password_hash'] != hash_password(data.password): return {"error": "아이디 또는 비밀번호가 틀립니다."}
    token = create_access_token(user['id'], user['username'])
    return {"message": "success", "token": token, "username": user['username']}

# --- 플래너 API ---
@app.get("/api/tasks/{query_date}")
async def get_tasks(query_date: str, owner_id: str = Depends(get_current_owner)):
    conn = get_db_connection()
    cursor = conn.cursor()
    dt = datetime.strptime(query_date, "%Y-%m-%d")
    js_day = str(dt.strftime("%w"))
    cursor.execute("SELECT * FROM records WHERE study_date = %s AND owner_id = %s ORDER BY id ASC", (query_date, owner_id))
    records = cursor.fetchall()
    cursor.execute("SELECT * FROM routines WHERE repeat_days LIKE %s AND owner_id = %s", ('%' + js_day + '%', owner_id))
    routines = cursor.fetchall()
    cursor.close()
    conn.close()
    tasks = []; record_routine_ids = set()
    for r in records:
        tasks.append({"uuid": f"record_{r['id']}", "type": "record", "id": r["id"], "subject": r["subject"], "target_minutes": r["target_minutes"], "duration_minutes": r["duration_minutes"], "is_completed": r["is_completed"], "routine_id": r["routine_id"], "repeat_days": ""})
        if r["routine_id"]: record_routine_ids.add(r["routine_id"])
    routine_dict = {rt["id"]: rt["repeat_days"] for rt in routines}
    for rt in routines:
        if rt["id"] not in record_routine_ids: tasks.append({"uuid": f"routine_{rt['id']}", "type": "routine", "id": rt["id"], "subject": rt["subject"], "target_minutes": rt["target_minutes"], "duration_minutes": 0, "is_completed": False, "routine_id": rt["id"], "repeat_days": rt["repeat_days"]})
    for t in tasks:
        if t["routine_id"] and t["routine_id"] in routine_dict: t["repeat_days"] = routine_dict[t["routine_id"]]
    return tasks

@app.post("/api/routines/")
async def create_routine(data: RoutineCreate, owner_id: str = Depends(get_current_owner)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO routines (subject, target_minutes, repeat_days, owner_id) VALUES (%s, %s, %s, %s)", (data.subject, data.target_minutes, data.repeat_days, owner_id))
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success"}

@app.post("/api/records/sync")
async def sync_record(data: SyncTask, owner_id: str = Depends(get_current_owner)):
    conn = get_db_connection()
    cursor = conn.cursor()
    if data.routine_id: cursor.execute("SELECT id FROM records WHERE study_date = %s AND routine_id = %s AND owner_id = %s", (data.date, data.routine_id, owner_id))
    else: cursor.execute("SELECT id FROM records WHERE study_date = %s AND subject = %s AND owner_id = %s", (data.date, data.subject, owner_id))
    row = cursor.fetchone()
    if row: cursor.execute("UPDATE records SET duration_minutes = %s, is_completed = %s WHERE id = %s", (data.duration_minutes, data.is_completed, row['id']))
    else: cursor.execute("INSERT INTO records (subject, study_date, duration_minutes, is_completed, target_minutes, routine_id, owner_id) VALUES (%s, %s, %s, %s, %s, %s, %s)", (data.subject, data.date, data.duration_minutes, data.is_completed, data.target_minutes, data.routine_id, owner_id))
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success"}

@app.put("/api/tasks/{task_type}/{task_id}/edit")
async def edit_task(task_type: str, task_id: int, data: TaskEdit, owner_id: str = Depends(get_current_owner)):
    conn = get_db_connection()
    cursor = conn.cursor()
    if task_type == 'routine' or data.repeat_days:
        r_id = task_id if task_type == 'routine' else cursor.execute("SELECT routine_id FROM records WHERE id=%s", (task_id,)).fetchone()['routine_id']
        cursor.execute("UPDATE routines SET subject = %s, target_minutes = %s, repeat_days = %s WHERE id = %s AND owner_id = %s", (data.subject, data.target_minutes, data.repeat_days, r_id, owner_id))
        cursor.execute("UPDATE records SET subject = %s, target_minutes = %s WHERE routine_id = %s AND owner_id = %s", (data.subject, data.target_minutes, r_id, owner_id))
    else:
        cursor.execute("UPDATE records SET subject = %s, target_minutes = %s WHERE id = %s AND owner_id = %s", (data.subject, data.target_minutes, task_id, owner_id))
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "success"}

@app.delete("/api/tasks/{task_type}/{task_id}")
async def delete_task(task_type: str, task_id: int, owner_id: str = Depends(get_current_owner)):
    conn = get_db_connection()
    cursor = conn.cursor()
    if task_type == 'routine': cursor.execute("DELETE FROM routines WHERE id = %s AND owner_id = %s", (task_id, owner_id))
    else: cursor.execute("DELETE FROM records WHERE id = %s AND owner_id = %s", (task_id, owner_id))
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "deleted"}

@app.get("/api/heatmap/")
async def get_heatmap(owner_id: str = Depends(get_current_owner)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TO_CHAR(study_date, 'YYYY-MM-DD') as date, SUM(duration_minutes) as total, SUM(target_minutes) as target FROM records WHERE owner_id = %s GROUP BY study_date", (owner_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [{"date": row['date'], "value": row['total'], "target": row['target']} for row in rows]

@app.get("/api/records/date/{query_date}")
async def get_daily_records(query_date: str, owner_id: str = Depends(get_current_owner)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subject, duration_minutes, is_completed, target_minutes FROM records WHERE study_date = %s AND owner_id = %s", (query_date, owner_id))
    records = cursor.fetchall()
    cursor.close()
    conn.close()
    return records

# 🌟 신규: 과목별 누적 통계 API
@app.get("/api/stats/")
async def get_stats(owner_id: str = Depends(get_current_owner)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT subject, SUM(duration_minutes) as total_minutes FROM records WHERE owner_id = %s AND duration_minutes > 0 GROUP BY subject ORDER BY total_minutes DESC", (owner_id,))
    stats = cursor.fetchall()
    cursor.close()
    conn.close()
    return stats

app.mount("/", StaticFiles(directory="static", html=True), name="static")