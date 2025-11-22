# main.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from teacher_api import router as teacher_router
from fastapi.staticfiles import StaticFiles



app = FastAPI(title="ClassSight - Teacher API")


CAM1_DIR = r"C:\Users\User\Desktop\HACKLOOP-2\camera1\proofs"



app.mount(
    "/static/cam1",
    StaticFiles(directory=CAM1_DIR),
    name="cam1"
)

print("SERVING CAM1 FROM:", CAM1_DIR)


# CORS for local development - restrict in prod
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(teacher_router)

@app.get("/")
def root():
    return {"message": "Teacher API running!"}
