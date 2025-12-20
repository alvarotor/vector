FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for PyTorch
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download the model during build to speed up startup
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY texts_ai.py .
COPY search_pb2.py .
COPY search_pb2_grpc.py .

CMD ["python", "texts_ai.py"]