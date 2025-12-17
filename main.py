import uuid, os, shutil
from fastapi import FastAPI, HTTPException, UploadFile, File, Form , BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse , FileResponse
from pydantic import BaseModel
from langgraph.types import Command
from agent import agency_agent_app 
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, HttpUrl
import os
from typing import Optional
from pathlib import Path
from ffmpeg_func import *

# ======================================================
# FastAPI Setup
# ======================================================

app = FastAPI(
    title="Offer Letter Generation API",
    description="API to generate offer letters and handle human-in-the-loop review before PDF creation.",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PDF_DIR = "generated_pdfs"
os.makedirs(PDF_DIR, exist_ok=True)

TEMP_DIR = Path("/tmp/video_processing")
TEMP_DIR.mkdir(exist_ok=True)

# ======================================================
# Input Model
# ======================================================

class OfferRequest(BaseModel):
    agency_name: str
    tenure: str
    fee: str
    requirement_list: list[str]
    joining_date: str
    client_name: str
    company_name: str = 'Creativity Unleashed'
    company_email: str
    company_mobile: str

class VideoEditRequest(BaseModel):
    crop_h: int
    crop_w: int
    crop_x: int
    crop_y: int
    edit_mode: str
    resize_h: int
    resize_w: int
    trim_end: float
    trim_start: float
    version_note: str
    video_url: HttpUrl

# ======================================================
# Helper
# ======================================================

def build_reference_url(pdf_path: str) -> str:
    base_url = "http://localhost:3000/admin/contract/view"
    filename = os.path.basename(pdf_path)
    return f"{base_url}/{filename}"


# ======================================================
# 1️⃣ Start the HITL flow — pause at interrupt
# ======================================================
app.mount("/files", StaticFiles(directory="files"), name="files")


@app.post("/start-letter-generation")
async def start_letter_generation(request: OfferRequest):
    """
    Starts a letter generation flow that pauses after generating the offer letter text
    for human review.
    """
    try:
        session_id = uuid.uuid4().hex[:8]

        inputs = {
            "agency_name": request.agency_name,
            "tenure": request.tenure,
            "fee": request.fee,
            "requirement_list": request.requirement_list,
            "joining_date": request.joining_date,
            "client_name": request.client_name,
            "company_name": request.company_name,
            "company_email": request.company_email,
            "company_mobile": request.company_mobile,
            "session_id": session_id
        }

        # Config to track this session
        config = {"configurable": {"thread_id": session_id}}

        print(f"Starting new letter generation session: {session_id}")

        # Run until it hits the interrupt()
        response = agency_agent_app.invoke(inputs, config)

        # Fetch the checkpoint ID
        latest_snapshot = agency_agent_app.get_state(config)
        checkpoint_id = latest_snapshot.config["configurable"]["checkpoint_id"]

        # response will contain interrupt data like {"letter_text": "..."}
        return {
            "session_id": session_id,
            "checkpoint_id": checkpoint_id,
            **response  # contains the "letter_text" + "message"
        }

    except Exception as e:
        print(f"Error starting letter generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================
# 2️⃣ Resume after human review 
# ======================================================

@app.post("/resume-letter-review")
async def resume_letter_review(body: dict):
    """
    Resumes the letter generation after user review.
    """
    try:
        print(f"body is {body.keys()}")
        session_id = body["session_id"]
        checkpoint_id = body["checkpoint_id"]
        edited_letter = body["edited_letter"]

        config = {
            "configurable": {
                "thread_id": session_id,
                "checkpoint_id": checkpoint_id
            }
        }

        print(f"Resuming letter generation for session {session_id}")

        command = Command(resume={"user_reviewed_text": edited_letter})
        response = agency_agent_app.invoke(command, config)

        latest_snapshot = agency_agent_app.get_state(config)

        return {
            "session_id": session_id,
            "message": "Letter review completed, resumed successfully.",
            "next_state": response,
            "checkpoint_id": latest_snapshot.config['configurable']['checkpoint_id']
        }

    except Exception as e:
        print(f" Error resuming letter review: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================
# 3️⃣ Upload edited PDFs (no change)
# ======================================================

@app.post("/upload-edited")
async def upload_edited_pdf(file: UploadFile = File(...), filename: str = Form(...)):
    try:
        save_path = os.path.join(PDF_DIR, f"edited_{filename}")
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        public_path = f"/files/edited_{filename}"
        print(f"Edited PDF uploaded: {public_path}")
        return JSONResponse({"success": True, "url": public_path})
    except Exception as e:
        print(f" Error saving edited PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"Validation error: {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# ======================================================
# Video Transformation Endpoint
# ======================================================


@app.post("/process-video")
async def process_video_endpoint(
    request: VideoEditRequest,
    background_tasks: BackgroundTasks
):
    """
    Process video with crop, resize, and trim operations.
    Returns the processed video file for download.
    """
    job_id = str(uuid.uuid4())
    input_file = TEMP_DIR / f"input_{job_id}.mov"
    output_file = TEMP_DIR / f"output_{job_id}.mp4"
    
    try:
        # Download video
        download_video(str(request.video_url), str(input_file))
        
        # Get video metadata
        width, height, duration = get_video_info(str(input_file))
        
        # Validate and adjust parameters
        final_crop_w = min(request.crop_w, width)
        final_crop_h = min(request.crop_h, height)
        final_trim_end = min(request.trim_end, duration)
        
        # Build processing parameters
        crop_params = (request.crop_x, request.crop_y, final_crop_w, final_crop_h)
        resize_params = (request.resize_w, request.resize_h)
        trim_params = (request.trim_start, final_trim_end)
        
        print(f"🎛️ Settings:")
        print(f"   Crop: {crop_params}")
        print(f"   Resize: {resize_params}")
        print(f"   Trim: {trim_params[0]:.1f}s → {trim_params[1]:.1f}s")
        
        # Process video
        process_video(
            str(input_file), 
            str(output_file), 
            crop_params, 
            resize_params, 
            trim_params
        )
        
        if not os.path.exists(output_file):
            raise Exception("Output file not created")
        
        # Schedule cleanup after response is sent
        background_tasks.add_task(cleanup_files, str(input_file), str(output_file))
        
        # Return file for download
        return FileResponse(
            path=str(output_file),
            media_type='video/mp4',
            filename=f"processed_{request.version_note.replace(' ', '_')}.mp4",
            background=background_tasks
        )
        
    except Exception as e:
        # Clean up on error
        cleanup_files(str(input_file), str(output_file))
        raise HTTPException(status_code=500, detail=str(e))





# ======================================================
# Health Check
# ======================================================

@app.get("/")
def read_root():
    return {"status": "Offer Letter API with Human-in-the-Loop is running 🚀"}
