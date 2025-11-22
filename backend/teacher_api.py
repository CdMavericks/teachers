# teacher_api.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
import pymysql
import sys
import os

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

# ------------------------------
#  CAM1 PROOF DIR  (LOCAL ONLY)
# ------------------------------
# This must match what you mounted in backend/main.py as StaticFiles(directory=...).
CAM1_PROOFS_DIR = r"C:\Users\User\Desktop\HACKLOOP-2\camera1\proofs"

# ------------------------------
# MODELS
# ------------------------------
class AttendanceRecord(BaseModel):
    student_usn: str
    status: str   # "Present" | "Absent"

class SaveAttendancePayload(BaseModel):
    class_id: int
    date: Optional[str] = None   # "YYYY-MM-DD" (optional, else today)
    records: List[AttendanceRecord]

class RevokePayload(BaseModel):
    class_id: int
    date: Optional[str] = None   # optional fake date

class FinalizePayload(BaseModel):
    class_id: int
    teacher_id: int
    date: Optional[str] = None   # optional fake date

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
@router.get("/classes")
def get_todays_classes(teacher_id: int, fake_time: str = None):
    try:
        # --- TIME PARSING ---
        if fake_time:
            fake_time_clean = fake_time.replace("+", " ")

            # Case 1: "YYYY-MM-DD"
            if "-" in fake_time_clean and len(fake_time_clean) == 10:
                try:
                    date_obj = datetime.strptime(fake_time_clean, "%Y-%m-%d")
                    weekday = date_obj.strftime("%A")
                except ValueError:
                    raise HTTPException(400, detail="Invalid date format. Expected YYYY-MM-DD")
            else:
                # Case 2: "Wednesday 11:10"
                parts = fake_time_clean.split(" ")
                if len(parts) != 2:
                    raise HTTPException(
                        400,
                        detail="fake_time must be 'Friday HH:MM' or 'YYYY-MM-DD'"
                    )

                weekday = parts[0].capitalize()
                timestr = parts[1]

                try:
                    datetime.strptime(timestr, "%H:%M")
                except Exception:
                    raise HTTPException(400, detail="Invalid time in fake_time (HH:MM)")
        else:
            now = datetime.now()
            weekday = now.strftime("%A")

        conn = db()
        with conn.cursor() as cur:
            cur.execute(
                """
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
                """,
                (teacher_id, weekday)
            )
            classes = cur.fetchall()

        conn.close()
        return classes

    except HTTPException:
        raise
    except Exception as e:
        print("!!! ERROR /teacher/classes:", e, file=sys.stderr)
        raise HTTPException(500, detail="Internal error in class lookup")

# ============================================================
# 3. GET STUDENTS IN CLASS + MERGE ATTENDANCE + CAM1/CAM2
# ============================================================
@router.get("/class/students")
def get_class_students(class_id: int, date_str: str = None):
    try:
        query_date = date_str if date_str else datetime.now().strftime("%Y-%m-%d")

        conn = db()
        with conn.cursor() as cur:
            # 1) Get section from timetable
            cur.execute("SELECT section FROM timetable WHERE class_id = %s", (class_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return {"error": "Class not found"}

            section = row["section"].strip()

            # 2) Students + teacher working copy (attendance) + cam1/cam2 flags
            sql = """
                SELECT 
                    s.usn,
                    s.student_name,

                    -- teacher working copy
                    COALESCE(a.status, 'Absent') AS current_status,

                    -- CAM1 flag
                    CASE 
                        WHEN cam1.student_usn IS NOT NULL THEN 1 
                        ELSE 0 
                    END AS cam1_present,

                    -- CAM2 flag
                    CASE
                        WHEN cam2.student_usn IS NOT NULL THEN 1
                        ELSE 0
                    END AS cam2_present

                FROM student_info s

                LEFT JOIN attendance a
                    ON a.student_usn = s.usn
                    AND a.class_id = %s
                    AND a.date = %s

                LEFT JOIN attendance_cam1 cam1
                    ON cam1.student_usn = s.usn
                    AND cam1.class_id = %s

                LEFT JOIN attendance_cam2 cam2
                    ON cam2.student_usn = s.usn
                    AND cam2.class_id = %s

                WHERE TRIM(s.student_section) = TRIM(%s)
                ORDER BY s.usn ASC;
            """
            cur.execute(sql, (class_id, query_date, class_id, class_id, section))
            students = cur.fetchall()

        conn.close()
        return {"students": students, "date_used": query_date}

    except Exception as e:
        print("!!! ERROR /teacher/class/students:", e, file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 4. CAM1 + CAM2 WRITE (for future real integration)
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
# 5. SAVE ATTENDANCE (teacher working copy -> attendance)
#    Option C base: attendance is working copy
# ============================================================
@router.post("/attendance/mark")
def save_attendance(payload: SaveAttendancePayload):
    try:
        class_id = payload.class_id
        records = payload.records
        date_value = payload.date or datetime.now().strftime("%Y-%m-%d")

        conn = db()
        with conn.cursor() as cur:

            # delete old entries for that date
            cur.execute(
                "DELETE FROM attendance WHERE class_id=%s AND date=%s",
                (class_id, date_value)
            )

            # insert all
            for r in records:
                cur.execute(
                    """
                    INSERT INTO attendance (class_id, student_usn, date, status)
                    VALUES (%s, UPPER(%s), %s, %s)
                    """,
                    (class_id, r.student_usn, date_value, r.status)
                )

        conn.commit()
        conn.close()

        return {"rows": len(records), "date": date_value}

    except Exception as e:
        print("!!! ERROR /teacher/attendance/mark:", e)
        raise HTTPException(status_code=500, detail=str(e))
# ============================================================
# 6. REVOKE ATTENDANCE (clear working copy for that day)
# ============================================================
@router.post("/attendance/revoke")
def revoke_attendance(payload: RevokePayload):
    try:
        class_id = payload.class_id
        date_str = payload.date or datetime.now().strftime("%Y-%m-%d")

        conn = db()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM attendance WHERE class_id=%s AND date=%s",
                (class_id, date_str)
            )
        conn.commit()
        conn.close()

        return {"msg": "Attendance revoked", "date": date_str}

    except Exception as e:
        print("!!! ERROR /teacher/attendance/revoke:", e, file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 7. FINALIZE ATTENDANCE -> final_attendance  (Option C)
#    Read from attendance (working copy) and UPSERT into final_attendance
# ============================================================
@router.post("/attendance/finalize")
def finalize_attendance(payload: FinalizePayload):
    try:
        class_id = payload.class_id
        teacher_id = payload.teacher_id
        date_str = payload.date or datetime.now().strftime("%Y-%m-%d")

        conn = db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT student_usn, status
                FROM attendance
                WHERE class_id=%s AND date=%s
            """, (class_id, date_str))
            rows = cur.fetchall()

            if not rows:
                conn.close()
                return {
                    "rows": 0,
                    "date": date_str,
                    "note": "No temporary attendance to finalize"
                }

            for r in rows:
                usn = r["student_usn"]
                status = r["status"] or "Absent"

                cur.execute("""
                    INSERT INTO final_attendance
                        (class_id, student_usn, date, final_status, teacher_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        final_status = VALUES(final_status),
                        teacher_id = VALUES(teacher_id),
                        locked_at = CURRENT_TIMESTAMP
                """, (class_id, usn, date_str, status, teacher_id))

        conn.commit()
        conn.close()

        return {"rows": len(rows), "date": date_str}

    except Exception as e:
        print("!!! ERROR /teacher/attendance/finalize:", e, file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 8. CAM1 PROOF LOOKUP
#    Checks local filesystem and returns URL if present
# ============================================================
@router.get("/proof/cam1")
def get_cam1_proof(student_usn: str, date: str):
    """
    For now we ignore 'date' in the filename and just look for:
        <CAM1_PROOFS_DIR>/<USN>.jpg

    Frontend:
      - Calls this endpoint
      - If exists=True → use returned URL in <img>
      - If exists=False → show "No CAM1 image available" text
    """
    try:
        if not CAM1_PROOFS_DIR:
            return {
                "exists": False,
                "url": None,
                "message": "CAM1 proof directory not configured"
            }

        fname = f"{student_usn}.jpg"
        fpath = os.path.join(CAM1_PROOFS_DIR, fname)

        if os.path.exists(fpath):
            return {
                "exists": True,
                "url": f"/static/cam1/{fname}"
            }

        return {
            "exists": False,
            "url": None,
            "message": "No image available"
        }

    except Exception as e:
        print("!!! ERROR /teacher/proof/cam1:", e, file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))
