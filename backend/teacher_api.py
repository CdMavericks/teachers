# teacher_api.py

from fastapi import APIRouter, HTTPException
from datetime import datetime
import pymysql
import sys

router = APIRouter(prefix="/teacher", tags=["Teacher"])


# ------------------------------
#  DB
# ------------------------------
def db():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="ClassSight123!",
        database="classsight_db",
        cursorclass=pymysql.cursors.DictCursor
    )


# ============================================================
# 1. GET TEACHER INFO BY FIREBASE UID
# ============================================================
@router.get("/info")
def get_teacher_info(firebase_uid: str):
    try:
        conn = db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT teacher_id, name, email
                FROM teachers
                WHERE firebase_uid = %s
                """,
                (firebase_uid,)
            )
            teacher = cur.fetchone()
        conn.close()

        if not teacher:
            raise HTTPException(status_code=404, detail="Teacher not found")

        return teacher

    except Exception as e:
        print("!!! ERROR /teacher/info:", e, file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 2. GET TODAY'S CLASSES  +  FAKE TIME SUPPORT
# ============================================================
# ============================================================
# 2. GET TODAY'S CLASSES  +  FAKE TIME SUPPORT (FIXED)
# ============================================================
@router.get("/classes")
def get_todays_classes(teacher_id: int, fake_time: str = None):
    try:
        # --- TIME PARSING ---
        if fake_time:
            fake_time_clean = fake_time.replace("+", " ")

            # NEW: Check if it's a date string (e.g., "2025-11-10")
            if "-" in fake_time_clean and len(fake_time_clean) == 10:
                try:
                    # It's a date. Parse it to get the weekday.
                    date_obj = datetime.strptime(fake_time_clean, "%Y-%m-%d")
                    weekday = date_obj.strftime("%A")
                except ValueError:
                    raise HTTPException(400, detail="Invalid date format. Expected YYYY-MM-DD")
            
            # ORIGINAL: Check if it's "Day Time" (e.g., "Wednesday 11:10")
            else:
                parts = fake_time_clean.split(" ")
                if len(parts) != 2:
                    raise HTTPException(400, detail="Time must be 'Friday HH:MM' or 'YYYY-MM-DD'")

                weekday = parts[0].capitalize()
                timestr = parts[1]

                # Validate time
                try:
                    datetime.strptime(timestr, "%H:%M")
                except:
                    raise HTTPException(400, detail="Invalid time in entered (HH:MM)")
        else:
            # Default to today if no fake_time
            now = datetime.now()
            weekday = now.strftime("%A")

        # --- DATABASE QUERY (no changes needed here) ---
        conn = db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    class_id,
                    section,
                    subject,
                    weekday,
                    TIME_FORMAT(start_time, '%%H:%%i') AS start_time,
                    TIME_FORMAT(end_time, '%%H:%%i') AS end_time
                FROM timetable
                WHERE teacher_id = %s
                AND LOWER(weekday) = LOWER(%s)
                ORDER BY start_time
            """, (teacher_id, weekday))

            classes = cur.fetchall()

        conn.close()
        return classes

    except HTTPException:
        raise
    except Exception as e:
        print("!!! ERROR /teacher/classes:", e, file=sys.stderr)
        raise HTTPException(500, detail="Internal error in class lookup")

# ============================================================
# 3. GET STUDENTS IN CLASS
# ============================================================
@router.get("/class/students")
def get_class_students(class_id: int, date_str: str = None):
    try:
        # Default to today if no date provided (matches your logic)
        query_date = date_str if date_str else datetime.now().strftime("%Y-%m-%d")

        conn = db()
        with conn.cursor() as cur:
            # 1. Get section
            cur.execute("SELECT section FROM timetable WHERE class_id = %s", (class_id,))
            row = cur.fetchone()
            if not row:
                return {"error": "Class not found"}
            section = row["section"].strip()

            # 2. Get Students + Current Attendance Status
            # We LEFT JOIN on the attendance table matching Class ID + Date + Student USN
            sql = """
                SELECT 
                    s.usn, 
                    s.student_name,
                    COALESCE(a.status, 'Absent') as current_status
                FROM student_info s
                LEFT JOIN attendance a 
                    ON s.usn = a.student_usn 
                    AND a.class_id = %s 
                    AND a.date = %s
                WHERE TRIM(s.student_section) = TRIM(%s)
                ORDER BY s.usn ASC
            """
            cur.execute(sql, (class_id, query_date, section))
            students = cur.fetchall()

        conn.close()
        return {"students": students, "date_used": query_date}

    except Exception as e:
        print("!!! ERROR /class/students:", e, file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 4. CAM1 + CAM2 TABLES
# ============================================================
@router.post("/cam1/add")
def cam1_add(class_id: int, student_usn: str):
    conn = db()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO attendance_cam1 (class_id, student_usn) VALUES (%s, %s)",
            (class_id, student_usn)
        )
    conn.commit()
    conn.close()
    return {"msg": "Recorded in CAM1"}


@router.post("/cam2/add")
def cam2_add(class_id: int, student_usn: str):
    conn = db()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO attendance_cam2 (class_id, student_usn) VALUES (%s, %s)",
            (class_id, student_usn)
        )
    conn.commit()
    conn.close()
    return {"msg": "Recorded in CAM2"}


# ============================================================
# 5. SAVE attendance (teacher final submit)
# ============================================================
@router.post("/attendance/mark")
def save_attendance(payload: dict):
    try:
        class_id = payload["class_id"]
        records = payload["records"]

        today = datetime.now().strftime("%Y-%m-%d")

        conn = db()
        with conn.cursor() as cur:

            # delete old entries for today (overwrite)
            cur.execute(
                "DELETE FROM attendance WHERE class_id=%s AND date=%s",
                (class_id, today)
            )

            # insert all
            for r in records:
                cur.execute(
                    """
                    INSERT INTO attendance (class_id, student_usn, date, status)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (class_id, r["student_usn"], today, r["status"])
                )

        conn.commit()
        conn.close()

        return {"rows": len(records), "date": today}

    except Exception as e:
        print("!!! ERROR /attendance/mark:", e, file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 6. REVOKE ATTENDANCE
# ============================================================
@router.post("/attendance/revoke")
def revoke_attendance(class_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        conn = db()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM attendance WHERE class_id=%s AND date=%s",
                (class_id, today)
            )

        conn.commit()
        conn.close()
        return {"msg": "Attendance revoked for today"}

    except Exception as e:
        print("!!! ERROR /attendance/revoke:", e, file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))

