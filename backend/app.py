from fastapi import FastAPI, HTTPException
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator
from typing import Union, Optional
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import uuid
import redis
import json
import os
import grpc
import requests

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://user:password@postgres:5432/db"
)
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
GRPC_PORT = os.environ.get("GRPC_PORT", "50051")
AUDIO_GRPC_PORT = os.environ.get("AUDIO_GRPC_PORT", "50052")
TRANSCRIBER_GRPC_PORT = os.environ.get("TRANSCRIBER_GRPC_PORT", "50053")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
redis_client = redis.Redis(host="localhost", port=REDIS_PORT, decode_responses=True)

Base = declarative_base()


class TextEntry(Base):
    __tablename__ = "texts"
    id = Column(String, primary_key=True, index=True)
    text = Column(Text, nullable=False)


# Base.metadata.create_all(bind=engine)  # Moved to startup event

app = FastAPI()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"Validation error on {request.url}: {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.on_event("startup")
def startup_event():
    # Skip database setup for now to allow LLM endpoint to work
    print("Skipping database setup for quick LLM testing")


class TextCreate(BaseModel):
    text: str


class TextResponse(BaseModel):
    id: str
    text: str


class SearchResult(BaseModel):
    id: str
    text: str


class AudioFromTextRequest(BaseModel):
    text: str
    format: str = "mp3"
    language: str = "en"
    voice: Optional[str] = None


class AudioFromIdRequest(BaseModel):
    id: Union[str, int]
    format: str = "mp3"
    language: str = "en"
    voice: Optional[str] = None

    @validator("id", pre=True)
    def validate_id(cls, v):
        if isinstance(v, int):
            return str(v)
        if isinstance(v, str):
            return v
        raise ValueError("id must be string or int")


class GenerateResponseRequest(BaseModel):
    text: str
    session_id: str
    lang: str = "en"


@app.post("/add_text", response_model=TextResponse)
def add_text(entry: TextCreate):
    db = SessionLocal()
    try:
        entry_id = str(uuid.uuid4())
        db_entry = TextEntry(id=entry_id, text=entry.text)
        db.add(db_entry)
        db.commit()
        db.refresh(db_entry)
        # Publish to Valkey
        redis_client.publish(
            "new_text", json.dumps({"uuid": entry_id, "text": entry.text})
        )
        return TextResponse(id=entry_id, text=entry.text)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to add text")
    finally:
        db.close()


class TranscribeAudioRequest(BaseModel):
    language: Union[str, None] = None  # Optional language hint ("en", "es", etc.)


@app.post("/transcribe_audio")
async def transcribe_audio(file: UploadFile = File(...), language: str = Form(None)):
    """Transcribe audio file to text and store transcription in database"""
    try:
        import transcribe_pb2
        import transcribe_pb2_grpc

        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        # Check file size (limit to 25MB)
        file_content = await file.read()
        if len(file_content) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File too large (max 25MB)")

        # Detect format from filename
        filename = file.filename.lower()
        if filename.endswith(".mp3"):
            format_type = "mp3"
        elif filename.endswith(".wav"):
            format_type = "wav"
        elif filename.endswith(".flac"):
            format_type = "flac"
        elif filename.endswith(".m4a") or filename.endswith(".aac"):
            format_type = "m4a"
        else:
            raise HTTPException(status_code=400, detail="Unsupported audio format")

        print(
            f"Transcribing audio: {file.filename} ({len(file_content)} bytes, {format_type})"
        )

        # Call transcriber_ai service
        with grpc.insecure_channel(
            f"localhost:{TRANSCRIBER_GRPC_PORT}",
            options=[("grpc.keepalive_timeout_ms", 300000)],  # 5 minutes timeout
        ) as channel:
            stub = transcribe_pb2_grpc.TranscriberServiceStub(channel)
            response = stub.TranscribeAudio(
                transcribe_pb2.TranscribeAudioRequest(
                    audio_data=file_content,
                    format=format_type,
                    language=language or "",  # Empty string for auto-detect
                    max_duration=300,  # 5 minutes max
                )
            )

        print(f"Transcription completed in {response.processing_time:.2f}s")

        # Return transcription without storing (for quick testing)
        return {
            "transcription": response.text,
            "detected_language": response.detected_language,
            "processing_time": response.processing_time,
            "confidence": getattr(response, "confidence", None),  # May not be available
        }

    except grpc.RpcError as e:
        print(f"gRPC error: {e.code()} - {e.details()}")
        if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise HTTPException(status_code=400, detail="Invalid audio file or format")
        elif e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
            raise HTTPException(status_code=408, detail="Transcription timeout")
        elif e.code() == grpc.StatusCode.UNAVAILABLE:
            raise HTTPException(
                status_code=503, detail="Transcription service unavailable"
            )
        else:
            raise HTTPException(status_code=500, detail="Transcription failed")
    except Exception as e:
        print(f"Transcription failed: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Transcription failed")


@app.get("/search", response_model=list[SearchResult])
def search(query: str):
    vector_ids = []
    try:
        import grpc
        import search_pb2
        import search_pb2_grpc

        # Call texts_ai for semantic search via gRPC
        with grpc.insecure_channel(f"localhost:{GRPC_PORT}") as channel:
            stub = search_pb2_grpc.SearchServiceStub(channel)
            response = stub.Search(search_pb2.SearchRequest(query=query))
            vector_ids = list(response.ids)
            print(f"Vector IDs: {vector_ids}")
    except Exception as e:
        print(f"Semantic search failed: {e}")
        return []

    # Get texts for the IDs
    db = SessionLocal()
    try:
        if vector_ids:
            texts_results = (
                db.query(TextEntry).filter(TextEntry.id.in_(vector_ids)).all()
            )
            return [SearchResult(id=r.id, text=r.text) for r in texts_results]
        else:
            return []
    finally:
        db.close()


@app.get("/search_literal", response_model=list[SearchResult])
def search_literal(query: str):
    # Literal search in PostgreSQL
    db = SessionLocal()
    try:
        literal_results = (
            db.query(TextEntry).filter(TextEntry.text.ilike(f"%{query}%")).all()
        )
        return [SearchResult(id=r.id, text=r.text) for r in literal_results]
    finally:
        db.close()


@app.delete("/delete_text/{entry_id}")
def delete_text(entry_id: str):
    db = SessionLocal()
    try:
        entry = db.query(TextEntry).filter(TextEntry.id == entry_id).first()
        if not entry:
            raise HTTPException(status_code=404, detail="Text not found")
        db.delete(entry)
        db.commit()
        # Publish to Valkey for Qdrant deletion
        redis_client.publish("delete_text", json.dumps({"uuid": entry_id}))
        return {"message": "Text deleted"}
    finally:
        db.close()


@app.post("/generate_audio_from_text")
def generate_audio_from_text(request: AudioFromTextRequest):
    print("generate_audio_from_text called")
    try:
        import grpc
        import audio_pb2
        import audio_pb2_grpc

        print(f"Connecting to audios_ai for text: {request.text[:50]}")
        print(f"Connecting to localhost:{AUDIO_GRPC_PORT}")
        with grpc.insecure_channel(
            f"localhost:{AUDIO_GRPC_PORT}",
            options=[("grpc.keepalive_timeout_ms", 120000)],
        ) as channel:
            stub = audio_pb2_grpc.AudioServiceStub(channel)
            response = stub.GenerateAudioFromText(
                audio_pb2.GenerateAudioFromTextRequest(
                    text=request.text, format=request.format, language=request.language, voice=request.voice
                )
            )
            print("Received response from audios_ai")
            media_type = "audio/mpeg" if request.format == "mp3" else "audio/wav"
            filename = f"{uuid.uuid4()}.{request.format}"
            audio_data = response.audio_data
            return StreamingResponse(
                iter([audio_data]),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
    except grpc.RpcError as e:
        print(f"gRPC error: {e.code()} - {e.details()}")
        if e.code() == grpc.StatusCode.UNAVAILABLE:
            raise HTTPException(status_code=503, detail="Audio service unavailable")
        elif e.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise HTTPException(status_code=400, detail="Invalid request parameters")
        else:
            raise HTTPException(status_code=500, detail="Audio generation failed")
    except Exception as e:
        print(f"Audio generation failed: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Audio generation failed")


@app.post("/generate_audio_from_id")
def generate_audio_from_id(request: AudioFromIdRequest):
    try:
        import grpc
        import audio_pb2
        import audio_pb2_grpc

        print(f"Connecting to audios_ai for id: {request.id}")
        with grpc.insecure_channel(
            f"localhost:{AUDIO_GRPC_PORT}",
            options=[("grpc.keepalive_timeout_ms", 120000)],
        ) as channel:
            stub = audio_pb2_grpc.AudioServiceStub(channel)
            response = stub.GenerateAudioFromId(
                audio_pb2.GenerateAudioFromIdRequest(
                    id=str(request.id), format=request.format, language=request.language, voice=request.voice
                )
            )
            print("Received response from audios_ai")
            media_type = "audio/mpeg" if request.format == "mp3" else "audio/wav"
            filename = f"{request.id}.{request.format}"
            audio_data = response.audio_data
            return StreamingResponse(
                iter([audio_data]),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
    except grpc.RpcError as e:
        print(f"gRPC error: {e.code()} - {e.details()}")
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Text not found")
        elif e.code() == grpc.StatusCode.UNAVAILABLE:
            raise HTTPException(status_code=503, detail="Audio service unavailable")
        elif e.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise HTTPException(status_code=400, detail="Invalid request parameters")
        else:
            raise HTTPException(status_code=500, detail="Audio generation failed")
    except Exception as e:
        print(f"Audio generation failed: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Audio generation failed")


@app.delete("/delete_all_texts")
def delete_all_texts():
    db = SessionLocal()
    try:
        db.query(TextEntry).delete()
        db.commit()
        # Publish to Valkey for Qdrant recreation
        redis_client.publish("delete_all", json.dumps({}))
        return {"message": "All texts deleted"}
    finally:
        db.close()


@app.post("/generate_response")
def generate_response(request: GenerateResponseRequest):
    """Generate a response using local LLM"""
    try:
        # Simple prompt without history
        if request.lang == "es":
            prompt = f"Eres un asistente útil. Responde de manera natural y concisa en español: {request.text}"
        else:
            prompt = f"You are a helpful assistant. Respond naturally and concisely in English: {request.text}"

        payload = {
            "model": "llama3.2:1b",
            "prompt": prompt,
            "stream": False
        }
        ollama_response = requests.post("http://localhost:11434/api/generate", json=payload, timeout=30)
        if ollama_response.status_code == 200:
            result = ollama_response.json()
            response_text = result["response"].strip()
            return {"response": response_text}
        else:
            raise HTTPException(status_code=500, detail=f"LLM error: {ollama_response.text}")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Ollama not reachable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Response generation failed: {str(e)}")