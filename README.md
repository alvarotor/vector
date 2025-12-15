# Vector Text Search System

A distributed system for storing and searching text documents using vector embeddings.

## Architecture

The system consists of two main services with a clear data flow:

### Data Flow
1. **Text Addition**: User sends text to FastAPI backend via `/add_text` endpoint
2. **Storage**: Text stored in PostgreSQL with generated UUID
3. **Notification**: UUID published to Redis message queue for vector processing
4. **Processing**: Text services consume the message, create vector embeddings using Sentence Transformers
5. **Vector Storage**: Embedding stored in Qdrant using PostgreSQL UUID as vector ID
6. **Search**: Vector similarity search returns UUIDs → Full text fetched from PostgreSQL
7. **Testing**: Sample script provides 19 comprehensive texts across technology, sports, and culinary topics

## Sample Data Benefits

✅ **Uniform Quality**: All texts are detailed, in-depth articles (300-500 words each)  
✅ **Topic Diversity**: Comprehensive coverage of technology, sports, and culinary domains  
✅ **Rich Embeddings**: Long-form content generates nuanced, high-quality vector representations  
✅ **Realistic Testing**: Mirrors production use cases with substantial, real-world text content  
✅ **Robust Evaluation**: Enables thorough testing of semantic similarity, clustering, and search accuracy

### Backend Service (`/backend`)
- **FastAPI application** for handling text storage and search requests
- **Dependencies**: FastAPI, SQLAlchemy, Pydantic, Redis client
- **Database**: PostgreSQL for persistent text storage with UUIDs
- **Message Queue**: Publishes new text UUIDs to Redis for vector processing
- **Vector Integration**: Triggers automatic vector embedding creation in Qdrant
- **Endpoints**:
  - `POST /add_text` - Add new text documents (stores in PostgreSQL, triggers vector creation)
  - `GET /search?query=<term>` - Semantic vector similarity search
  - `GET /search_literal?query=<term>` - Literal text matching search
  - `DELETE /delete_text/{id}` - Remove specific text by ID
  - `DELETE /delete_all_texts` - Remove all texts

### Text Services (`/texts_ai`)
- **Background processor** that creates vector embeddings for new texts
- **Dependencies**: Sentence Transformers, Qdrant client, Redis client
- **Vector Database**: Qdrant for similarity search using PostgreSQL UUIDs as vector IDs
- **Message Queue**: Subscribes to Redis for new text notifications

## Project Structure

```
/vector/
├── backend/
│   ├── requirements.txt       # FastAPI, SQLAlchemy, Pydantic, Redis
│   ├── Dockerfile
│   └── app.py                 # Full FastAPI app with PostgreSQL
├── texts_ai/
│   ├── requirements.txt       # Redis, Sentence Transformers, Qdrant
│   ├── Dockerfile
│   └── texts_ai.py       # Vector processing service
├── docker-compose.yml         # Multi-service orchestration
├── add_samples.sh         # Sample data script (uses API)
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
```bash
curl "http://localhost:8000/search?query=machine%20learning"
```

### Literal Search (Text matching)
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