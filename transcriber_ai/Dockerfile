FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for audio processing and PyTorch
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir torch && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download Whisper model for offline operation
RUN python -c "import whisper; whisper.load_model('base')"

COPY . .

EXPOSE 50053

CMD ["python", "transcriber_ai.py"]