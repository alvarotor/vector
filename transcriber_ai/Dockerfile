FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for audio processing and PyTorch
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 50053

CMD ["python", "transcriber_ai.py"]