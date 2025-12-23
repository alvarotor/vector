from fastapi import FastAPI, HTTPException
from fastapi import FastAPI, File, Form, UploadFile, Request
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
import time

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://user:password@postgres:5432/db"
)
REDIS_HOST = os.environ.get("REDIS_HOST", "valkey")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
GRPC_PORT = os.environ.get("GRPC_PORT", "50051")
AUDIO_GRPC_HOST = os.environ.get("AUDIO_GRPC_HOST", "audios_ai")
AUDIO_GRPC_PORT = os.environ.get("AUDIO_GRPC_PORT", "50052")
TRANSCRIBER_GRPC_HOST = os.environ.get("TRANSCRIBER_GRPC_HOST", "transcriber_ai")
TRANSCRIBER_GRPC_PORT = os.environ.get("TRANSCRIBER_GRPC_PORT", "50053")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

Base = declarative_base()


class TextEntry(Base):
    __tablename__ = "texts"
    id = Column(String, primary_key=True, index=True)
    text = Column(Text, nullable=False)


# Base.metadata.create_all(bind=engine)  # Moved to startup event

app = FastAPI()

# Add CORS middleware
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    session_id: Union[str, None] = None  # Optional session ID for language persistence


@app.post("/transcribe_audio")
async def transcribe_audio(request: Request, file: UploadFile = File(...), language: str = Form(None), session_id: str = Form(None)):
    """Transcribe audio file to text and store transcription in database"""
    endpoint_start = time.time()
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

        user_agent = request.headers.get("User-Agent", "unknown")
        print(
            f"Transcribe endpoint from {user_agent}: {file.filename} ({len(file_content)} bytes, {format_type})"
        )

        # Check for stored language
        stored_lang = None
        if session_id:
            lang_key = f"lang:{session_id}"
            stored_lang = redis_client.get(lang_key)
            if stored_lang:
                print(f"Using stored language for session {session_id}: {stored_lang}")
                language = stored_lang

        # Call transcriber_ai service
        grpc_start = time.time()
        with grpc.insecure_channel(
            f"{TRANSCRIBER_GRPC_HOST}:{TRANSCRIBER_GRPC_PORT}",
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
        grpc_time = time.time() - grpc_start
        print(f"gRPC call to transcriber_ai: {grpc_time:.2f}s")

        print(f"Transcription completed in {response.processing_time:.2f}s")
        total_endpoint_time = time.time() - endpoint_start
        print(f"Total transcribe endpoint time: {total_endpoint_time:.2f}s")

        # Store detected language for session
        if session_id and response.detected_language in ["en", "es"]:
            lang_key = f"lang:{session_id}"
            redis_client.set(lang_key, response.detected_language, ex=86400)  # Expire in 1 day
            print(f"Stored language {response.detected_language} for session {session_id}")

        # Use stored language if available, else detected
        effective_lang = stored_lang if stored_lang else response.detected_language

        # Return transcription without storing (for quick testing)
        return {
            "transcription": response.text,
            "detected_language": response.detected_language,
            "effective_language": effective_lang,
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
        with grpc.insecure_channel(f"texts_ai:{GRPC_PORT}") as channel:
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

        print(f"Connecting to {AUDIO_GRPC_HOST} for text: {request.text[:50]}")
        print(f"Connecting to {AUDIO_GRPC_HOST}:{AUDIO_GRPC_PORT}")
        with grpc.insecure_channel(
            f"{AUDIO_GRPC_HOST}:{AUDIO_GRPC_PORT}",
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

        print(f"Connecting to {AUDIO_GRPC_HOST} for id: {request.id}")
        with grpc.insecure_channel(
            f"{AUDIO_GRPC_HOST}:{AUDIO_GRPC_PORT}",
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
    """Generate a response using local LLM with conversation history"""
    try:
        # Load conversation history
        history_key = f"conversation:{request.session_id}"
        history = redis_client.lrange(history_key, 0, -1)
        print(f"Loaded history for {request.session_id}: {len(history)} messages")

        # Add user message
        user_msg = f"User: {request.text}"
        redis_client.rpush(history_key, user_msg)
        history.append(user_msg)
        print(f"Added user message: {request.text}")

        # Build prompt with history
        if request.lang == "es":
            system_prompt = "Eres un asistente útil. Responde de manera natural y concisa en español."
        else:
            system_prompt = "You are a helpful assistant. Respond naturally and concisely in English."

        conversation_text = "\n".join(history[-10:])  # Last 10 messages
        prompt = f"{system_prompt}\n\n{conversation_text}\nAssistant:"
        print(f"Prompt length: {len(prompt)} characters")

        payload = {
            "model": "llama3.2:1b",
            "prompt": prompt,
            "stream": False
        }
        print(f"Calling Ollama at {OLLAMA_URL}...")
        ollama_response = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=30)
        print(f"Ollama response status: {ollama_response.status_code}")
        if ollama_response.status_code == 200:
            result = ollama_response.json()
            response_text = result["response"].strip()
            print(f"Ollama response: {response_text[:100]}...")
            # Add AI response to history
            ai_msg = f"Assistant: {response_text}"
            redis_client.rpush(history_key, ai_msg)
            # Expire after 1 day
            redis_client.expire(history_key, 86400)
            return {"response": response_text}
        else:
            print(f"Ollama error: {ollama_response.text}")
            raise HTTPException(status_code=500, detail=f"LLM error: {ollama_response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Ollama not reachable: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ollama not reachable: {str(e)}")
    except Exception as e:
        print(f"Response generation failed: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Response generation failed: {str(e)}")