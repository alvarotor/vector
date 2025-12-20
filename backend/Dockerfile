FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir grpcio-tools

COPY app.py .
COPY search_pb2.py .
COPY search_pb2_grpc.py .

# Generate protobuf files
COPY transcribe.proto .
COPY audio.proto .
RUN python -m grpc_tools.protoc --python_out=. --grpc_python_out=. -I. transcribe.proto
RUN python -m grpc_tools.protoc --python_out=. --grpc_python_out=. -I. audio.proto

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]