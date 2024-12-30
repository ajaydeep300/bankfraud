from fastapi import FastAPI, UploadFile, File, Form

import os

# Import the new methods from snow
from app.snow import set_file_paths, main as snow_main
from app.bancorp import main as bancorp_main
from app.narrative import run_narrative_workflow
app = FastAPI()




# Ensure an uploads directory exists
UPLOAD_DIR = "./uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)



@app.get("/")
def read_root():
    return {"message": "Welcome to the Fraud Detection API! Please use the correct endpoints for your tasks."}


@app.post("/upload/")
async def upload_files(
    file1: UploadFile = File(...),
    file2: UploadFile = File(...),
    file3: UploadFile = File(...)
):
    """
    Endpoint that receives 3 Excel files via multipart/form-data.
    Saves them locally, then triggers snow.py's logic to parse & upload to Snowflake.
    """
    # Save files locally
    saved_paths = []
    for idx, file in enumerate([file1, file2, file3], 1):
        local_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(local_path, "wb") as f:
            f.write(await file.read())
        saved_paths.append(local_path)

    # Override the global file_paths in snow.py
    set_file_paths(saved_paths)

    # Execute snow.py's main(), which processes each file in file_paths
    snow_main()

    return {"message": "Files uploaded and processed successfully."}


@app.post("/analyze/")
def analyze_data():
    """
    Runs the entire 'bancorp.py' analysis flow 
    (including writing responses_log.txt).
    """
    bancorp_main()
    return {
        "message": "Analysis complete",
        "analysis_file_path": "files/responses_log.txt"
    }

@app.post("/narrative/")
async def narrative_endpoint(
    files: list[UploadFile], 
    analysis_file: str = Form(None)
):
    saved_paths = []
    for f in files:
        local_path = os.path.join(UPLOAD_DIR, f.filename)
        with open(local_path, "wb") as out_file:
            out_file.write(await f.read())
        saved_paths.append(local_path)

    # Now pass the file paths & optional analysis_file to your narrative function
    # (assuming 'analysis_file' is already on disk, or you can handle it similarly)
    run_narrative_workflow(saved_paths, analysis_file=analysis_file)
    return {"message": "Narrative analysis complete"}

