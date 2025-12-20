import json
import redis
import grpc
import threading
from concurrent import futures
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import search_pb2
import search_pb2_grpc
import os

# Initialize
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", 6333))
GRPC_PORT = os.environ.get("GRPC_PORT", "50051")

redis_client = redis.Redis(host="valkey", port=REDIS_PORT, decode_responses=True)
model = SentenceTransformer("all-MiniLM-L6-v2")
qdrant_client = QdrantClient(host="qdrant", port=QDRANT_PORT)


class SearchServicer(search_pb2_grpc.SearchServiceServicer):
    def Search(self, request, context):
        query = request.query
        # Vector similarity search
        query_embedding = model.encode(query).tolist()
        vector_results = qdrant_client.query_points(
            collection_name="texts", query=query_embedding, limit=10
        )
        # Debug: print query and scores
        print(f"Query: {query}")
        for hit in vector_results.points:
            print(f"ID: {hit.id}, Score: {hit.score}")
        # Filter by similarity score to ensure relevant results
        vector_ids = [hit.id for hit in vector_results.points if hit.score > 0.3]
        print(f"Filtered IDs: {vector_ids}")
        return search_pb2.SearchResponse(ids=vector_ids)


# Create collection if not exists
collection_name = "texts"
if not qdrant_client.collection_exists(collection_name):
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )


def process_message(message):
    try:
        data = json.loads(message["data"])
        if message["channel"] == "new_text":
            uuid = data["uuid"]
            text = data["text"]
            # Create embedding
            embedding = model.encode(text).tolist()
            # Upsert to Qdrant
            qdrant_client.upsert(
                collection_name=collection_name,
                points=[PointStruct(id=uuid, vector=embedding, payload={"text": text})],
            )
            print(f"Processed text: {uuid}")
        elif message["channel"] == "delete_text":
            uuid = data["uuid"]
            # Delete from Qdrant
            qdrant_client.delete(
                collection_name=collection_name, points_selector=[uuid]
            )
            print(f"Deleted text: {uuid}")
        elif message["channel"] == "delete_all":
            # Recreate collection to clear all
            qdrant_client.recreate_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )
            print("Recreated collection: all texts deleted")
    except Exception as e:
        print(f"Error processing message: {e}")


# Run gRPC server in thread
def run_grpc():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    search_pb2_grpc.add_SearchServiceServicer_to_server(SearchServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    server.start()
    server.wait_for_termination()


threading.Thread(target=run_grpc, daemon=True).start()

# Subscribe
pubsub = redis_client.pubsub()
pubsub.subscribe(
    **{
        "new_text": process_message,
        "delete_text": process_message,
        "delete_all": process_message,
    }
)

print("TextServices listening for new texts...")
for message in pubsub.listen():
    if message["type"] == "message":
        process_message(message)
