from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import uuid
import redis
import json
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://user:password@postgres:5432/db"
)
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
GRPC_PORT = os.environ.get("GRPC_PORT", "50051")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
redis_client = redis.Redis(host="valkey", port=REDIS_PORT, decode_responses=True)

Base = declarative_base()


class TextEntry(Base):
    __tablename__ = "texts"
    id = Column(String, primary_key=True, index=True)
    text = Column(Text, nullable=False)


# Base.metadata.create_all(bind=engine)  # Moved to startup event

app = FastAPI()


@app.on_event("startup")
def startup_event():
    # Wait for database to be ready and create tables
    import time

    max_retries = 30
    for i in range(max_retries):
        try:
            Base.metadata.create_all(bind=engine)
            print("Database tables created successfully")
            return
        except Exception as e:
            print(
                f"Database not ready, retrying in 2 seconds... ({i + 1}/{max_retries})"
            )
            time.sleep(2)
    raise Exception("Could not connect to database after retries")


class TextCreate(BaseModel):
    text: str


class TextResponse(BaseModel):
    id: str
    text: str


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
    finally:
        db.close()


@app.get("/search", response_model=list[str])
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
            return [r.text for r in texts_results]
        else:
            return []
    finally:
        db.close()


@app.get("/search_literal", response_model=list[str])
def search_literal(query: str):
    # Literal search in PostgreSQL
    db = SessionLocal()
    try:
        literal_results = (
            db.query(TextEntry).filter(TextEntry.text.ilike(f"%{query}%")).all()
        )
        return [r.text for r in literal_results]
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
