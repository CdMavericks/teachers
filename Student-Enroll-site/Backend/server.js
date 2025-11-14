// server.js — FINAL CLEANED, BUG-FIXED, ALL FEATURES KEPT

import express from "express";
import cors from "cors";
import mysql from "mysql2/promise";
import { v2 as cloudinary } from "cloudinary";
import dotenv from "dotenv";

dotenv.config();

/* ---------------------------------------------------------
   ENV VALIDATION
---------------------------------------------------------- */
const requiredEnvs = [
  "CLOUDINARY_CLOUD_NAME",
  "CLOUDINARY_API_KEY",
  "CLOUDINARY_API_SECRET",
  "DB_HOST",
  "DB_USER",
  "DB_NAME",
];

const missing = requiredEnvs.filter((k) => !process.env[k]);
if (missing.length) {
  console.error("❌ Missing ENV variables:", missing.join(", "));
  process.exit(1);
}

/* ---------------------------------------------------------
   EXPRESS
---------------------------------------------------------- */
const app = express();
app.use(cors());
app.use(express.json({ limit: "50mb" }));

/* ---------------------------------------------------------
   CLOUDINARY
---------------------------------------------------------- */
cloudinary.config({
  cloud_name: process.env.CLOUDINARY_CLOUD_NAME,
  api_key: process.env.CLOUDINARY_API_KEY,
  api_secret: process.env.CLOUDINARY_API_SECRET,
});

/* ---------------------------------------------------------
   MYSQL CONNECT
---------------------------------------------------------- */
const db = await mysql.createConnection({
  host: process.env.DB_HOST,
  user: process.env.DB_USER,
  port: Number(process.env.DB_PORT || 3306),
  password: process.env.DB_PASSWORD,
  database: process.env.DB_NAME,
  ssl:
    process.env.DB_SSL === "true" ? { rejectUnauthorized: false } : undefined,
});

console.log("✔️ Connected to MySQL");

/* ---------------------------------------------------------
   TABLES
---------------------------------------------------------- */
await db.execute(`
  CREATE TABLE IF NOT EXISTS enrollments (
    user_id VARCHAR(200) PRIMARY KEY,
    usn VARCHAR(50),
    student_name VARCHAR(255),
    student_branch VARCHAR(50),
    student_section VARCHAR(10),
    url_frontal TEXT,
    url_left TEXT,
    url_right TEXT,
    url_up TEXT,
    url_down TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      ON UPDATE CURRENT_TIMESTAMP
  );
`);
console.log("✔️ enrollments table ready");

await db.execute(`
  CREATE TABLE IF NOT EXISTS student_info (
    user_id VARCHAR(200) PRIMARY KEY,
    usn VARCHAR(20),
    student_name VARCHAR(255),
    student_branch VARCHAR(50),
    student_section VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      ON UPDATE CURRENT_TIMESTAMP
  );
`);
console.log("✔️ student_info table ready");

/* ---------------------------------------------------------
   HELPERS
---------------------------------------------------------- */
function isBase64Image(str) {
  return typeof str === "string" && str.startsWith("data:image");
}

/* ---------------------------------------------------------
   /enroll — one frontal image
---------------------------------------------------------- */
app.post("/enroll", async (req, res) => {
  try {
    const { userId, usn, studentName, studentBranch, studentSection, image } =
      req.body;

    if (!userId)
      return res.status(400).json({ status: "error", error: "Missing userId" });
    if (!usn)
      return res.status(400).json({ status: "error", error: "Missing usn" });

    if (!image || !isBase64Image(image)) {
      return res.status(400).json({
        status: "error",
        error: "Valid base64 frontal image required",
      });
    }

    const usnSafe = usn.trim().toUpperCase();

    const uploaded = await cloudinary.uploader.upload(image, {
      folder: `face_enrollments/${usnSafe}`,
      public_id: "frontal",
      overwrite: true,
      resource_type: "image",
    });

    const frontalUrl = uploaded.secure_url;

    await db.execute(
      `
      INSERT INTO enrollments
        (user_id, usn, student_name, student_branch, student_section,
         url_frontal, url_left, url_right, url_up, url_down)
      VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)
      ON DUPLICATE KEY UPDATE
        usn = VALUES(usn),
        student_name = VALUES(student_name),
        student_branch = VALUES(student_branch),
        student_section = VALUES(student_section),
        url_frontal = VALUES(url_frontal),
        url_left = NULL,
        url_right = NULL,
        url_up = NULL,
        url_down = NULL,
        updated_at = CURRENT_TIMESTAMP;
    `,
      [
        userId,
        usnSafe,
        studentName || null,
        studentBranch || null,
        studentSection || null,
        frontalUrl,
      ]
    );

    return res.json({ status: "success", url_frontal: frontalUrl });
  } catch (err) {
    console.error("ENROLL ERROR:", err);
    return res.status(500).json({ status: "error", error: err.message });
  }
});

/* ---------------------------------------------------------
   /saveStudentInfo — cleans studentName
---------------------------------------------------------- */
app.post("/saveStudentInfo", async (req, res) => {
  try {
    let { userId, usn, studentName, studentBranch, studentSection } = req.body;

    if (!userId || !usn || !studentName || !studentBranch || !studentSection)
      return res.status(400).json({ status: "error", error: "Missing fields" });

    // Remove USN from name automatically
    const fixedName = studentName.replace(usn, "").trim();

    await db.execute(
      `
      INSERT INTO student_info 
        (user_id, usn, student_name, student_branch, student_section)
      VALUES (?, ?, ?, ?, ?)
      ON DUPLICATE KEY UPDATE
        usn = VALUES(usn),
        student_name = VALUES(student_name),
        student_branch = VALUES(student_branch),
        student_section = VALUES(student_section),
        updated_at = CURRENT_TIMESTAMP
    `,
      [userId, usn, fixedName, studentBranch, studentSection]
    );

    res.json({ status: "success" });
  } catch (err) {
    console.error("SAVE STUDENT INFO ERROR:", err);
    res.status(500).json({ status: "error", error: err.message });
  }
});

/* ---------------------------------------------------------
   /getEnrollment
---------------------------------------------------------- */
app.get("/getEnrollment", async (req, res) => {
  try {
    const userId = req.query.userId;
    if (!userId)
      return res.status(400).json({ status: "error", error: "Missing userId" });

    const [rows] = await db.execute(
      `SELECT user_id, usn, student_name, student_branch, student_section, url_frontal
       FROM enrollments WHERE user_id = ? LIMIT 1`,
      [userId]
    );

    if (!rows.length) return res.json({ status: "error", error: "not_found" });

    return res.json({ status: "success", ...rows[0] });
  } catch (err) {
    console.error("GET ENROLLMENT ERROR:", err);
    return res.status(500).json({ status: "error", error: err.message });
  }
});

/* ---------------------------------------------------------
   /status — master flow state
---------------------------------------------------------- */
app.get("/status", async (req, res) => {
  try {
    const userId = req.query.userId;
    if (!userId)
      return res.status(400).json({ status: "error", error: "Missing userId" });

    const [infoRows] = await db.execute(
      `SELECT * FROM student_info WHERE user_id = ? LIMIT 1`,
      [userId]
    );

    const [enrollRows] = await db.execute(
      `SELECT * FROM enrollments WHERE user_id = ? LIMIT 1`,
      [userId]
    );

    const profileSaved = infoRows.length > 0;
    const photoEnrolled =
      enrollRows.length > 0 && enrollRows[0].url_frontal != null;

    return res.json({
      status: "success",
      profileSaved,
      photoEnrolled,
      student_info: profileSaved ? infoRows[0] : null,
      enrollment: enrollRows.length ? enrollRows[0] : null,
    });
  } catch (err) {
    console.error("STATUS ERROR:", err);
    return res.status(500).json({ status: "error", error: err.message });
  }
});

/* ---------------------------------------------------------
   START
---------------------------------------------------------- */
const PORT = process.env.PORT || 5000;
app.listen(PORT, () => console.log(`🚀 Server running on port ${PORT}`));
