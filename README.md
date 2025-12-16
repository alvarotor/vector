# Vector Text Search System

A distributed system for storing and searching text documents using vector embeddings.

## Architecture

The system consists of three main services with a clear data flow:

### Data Flow
1. **Text Addition**: User sends text to FastAPI backend via `/add_text` endpoint
2. **Storage**: Text stored in PostgreSQL with generated UUID
3. **Notification**: UUID published to Redis message queue for vector processing
4. **Processing**: Text services consume the message, create vector embeddings using Sentence Transformers
5. **Vector Storage**: Embedding stored in Qdrant using PostgreSQL UUID as vector ID
6. **Search**: Vector similarity search returns UUIDs → Full text fetched from PostgreSQL
7. **Audio Generation**: Optional audio synthesis from text or text ID using Google TTS (gTTS)
8. **Speech-to-Text**: Optional audio transcription using OpenAI Whisper (local, offline)
9. **Transcription Storage**: Transcribed text stored in PostgreSQL with new UUID
10. **Testing**: Sample script provides 19 comprehensive texts across technology, sports, and culinary topics

## Sample Data Benefits

✅ **Uniform Quality**: All texts are detailed, in-depth articles (300-500 words each)  
✅ **Topic Diversity**: Comprehensive coverage of technology, sports, and culinary domains  
✅ **Rich Embeddings**: Long-form content generates nuanced, high-quality vector representations  
✅ **Realistic Testing**: Mirrors production use cases with substantial, real-world text content  
✅ **Robust Evaluation**: Enables thorough testing of semantic similarity, clustering, and search accuracy

### Backend Service (`/backend`)
- **FastAPI application** for handling text storage, search, and audio generation requests
- **Dependencies**: FastAPI, SQLAlchemy, Pydantic, Redis client, gRPC clients
- **Database**: PostgreSQL for persistent text storage with UUIDs
- **Message Queue**: Publishes new text UUIDs to Redis for vector processing
- **Vector Integration**: Triggers automatic vector embedding creation in Qdrant
- **Audio Integration**: Calls audios_ai service for text-to-speech generation
- **Endpoints**:
  - `POST /add_text` - Add new text documents (stores in PostgreSQL, triggers vector creation)
  - `GET /search?query=<term>` - Semantic vector similarity search
  - `GET /search_literal?query=<term>` - Literal text matching search
  - `DELETE /delete_text/{id}` - Remove specific text by ID
  - `DELETE /delete_all_texts` - Remove all texts
  - `POST /generate_audio_from_text` - Generate audio from provided text
  - `POST /generate_audio_from_id` - Generate audio from text by ID
  - `POST /transcribe_audio` - Transcribe audio file to text and store result

### Text Services (`/texts_ai`)
- **Background processor** that creates vector embeddings for new texts
- **Dependencies**: Sentence Transformers, Qdrant client, Redis client
- **Vector Database**: Qdrant for similarity search using PostgreSQL UUIDs as vector IDs
- **Message Queue**: Subscribes to Redis for new text notifications

### Audio Services (`/audios_ai`)
- **gRPC service** for text-to-speech synthesis using Google TTS (gTTS)
- **Dependencies**: gTTS, SQLAlchemy, gRPC
- **Database**: PostgreSQL for fetching text by ID
- **Audio Generation**: Converts text to MP3/WAV audio on-demand
- **Endpoints**:
  - `GenerateAudioFromText` - Synthesize audio from input text
  - `GenerateAudioFromId` - Synthesize audio from text stored by ID

### Transcription Services (`/transcriber_ai`)
- **gRPC service** for speech-to-text transcription using OpenAI Whisper
- **Dependencies**: OpenAI Whisper, PyTorch, torchaudio, gRPC
- **Processing**: Local offline transcription (no cloud costs)
- **Languages**: English and Spanish support with auto-detection
- **Audio Support**: MP3, WAV, FLAC, M4A formats
- **Endpoints**:
  - `TranscribeAudio` - Transcribe audio file to text

## Project Structure

```
/vector/
├── backend/
│   ├── requirements.txt       # FastAPI, SQLAlchemy, Pydantic, Redis
│   ├── Dockerfile
│   ├── app.py                 # Full FastAPI app with PostgreSQL
│   ├── audio_pb2.py           # gRPC stubs for audio service
│   └── audio_pb2_grpc.py      # gRPC stubs for audio service
├── texts_ai/
│   ├── requirements.txt       # Redis, Sentence Transformers, Qdrant
│   ├── Dockerfile
│   └── texts_ai.py            # Vector processing service
├── audios_ai/
│   ├── requirements.txt       # gTTS, SQLAlchemy, gRPC
│   ├── Dockerfile
│   ├── audio.proto            # gRPC service definition
│   ├── audio_pb2.py           # gRPC stubs
│   ├── audio_pb2_grpc.py      # gRPC stubs
│   └── audios_ai.py           # Audio generation service
├── transcriber_ai/
│   ├── requirements.txt       # Whisper, PyTorch, gRPC
│   ├── Dockerfile
│   ├── transcribe.proto       # gRPC service definition
│   ├── transcribe_pb2.py      # gRPC stubs
│   ├── transcribe_pb2_grpc.py # gRPC stubs
│   └── transcriber_ai.py      # Speech-to-text service
├── docker-compose.yml         # Multi-service orchestration
├── add_samples.sh             # Sample data script (uses API)
└── README.md                  # This file
```

## Running the System

### Full System (with databases)
```bash
docker compose up --build
```

### Individual Services
```bash
# Backend service
cd backend
pip install -r requirements.txt
uvicorn app:app --reload

# Text services (requires Redis and Qdrant running)
cd texts_ai
pip install -r requirements.txt
python texts_ai.py

# Transcription services
cd transcriber_ai
pip install -r requirements.txt
python transcriber_ai.py
```

## Adding Sample Data

Run the sample script to populate the system (requires running services):

```bash
# Start the services first
docker compose up -d

# Then add sample data via API
./add_samples.sh  # Adds 19-20 comprehensive texts on tech, sports, and food topics
```

## API Usage

### Add Text
```bash
curl -X POST "http://localhost:8000/add_text" \
     -H "Content-Type: application/json" \
     -d '{"text": "Your text content here"}'
```

### Semantic Search (Vector-based)
Returns a list of objects with `id` and `text` fields for semantically similar texts.
```bash
curl "http://localhost:8000/search?query=machine%20learning"
```

### Literal Search (Text matching)
Returns a list of objects with `id` and `text` fields for texts containing the query string.
```bash
curl "http://localhost:8000/search_literal?query=machine%20learning"
```

### Delete Text by ID
```bash
curl -X DELETE "http://localhost:8000/delete_text/{id}"
```

### Delete All Texts
```bash
curl -X DELETE "http://localhost:8000/delete_all_texts"
```

### Generate Audio from Text
```bash
curl -X POST "http://localhost:8000/generate_audio_from_text" \
     -H "Content-Type: application/json" \
     -d '{"text": "Hello world", "format": "mp3"}' \
     -O  # Downloads the audio file
```

### Generate Audio from Text ID
```bash
curl -X POST "http://localhost:8000/generate_audio_from_id" \
     -H "Content-Type: application/json" \
     -d '{"id": "your-text-id", "format": "wav"}' \
     -O  # Downloads the audio file
```

### Transcribe Audio to Text
Transcribes audio files and stores the transcription as searchable text.
```bash
curl -X POST "http://localhost:8000/transcribe_audio" \
     -F "file=@audio_file.mp3" \
     -F "language=en"  # Optional: "en", "es", or omit for auto-detect
```

**Response:**
```json
{
  "text_id": "uuid-here",
  "transcription": "Your transcribed text...",
  "detected_language": "en",
  "processing_time": 2.3
}
```