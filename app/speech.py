# app/speech.py
import whisper
import os
import uuid
import shutil

model = whisper.load_model("base")

def save_temp_file(upload_file):
    file_id = str(uuid.uuid4())
    file_path = f"temp_{file_id}.wav"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)

    return file_path

def transcribe_audio(file_path: str):
    result = model.transcribe(file_path)
    os.remove(file_path)
    return result["text"]
