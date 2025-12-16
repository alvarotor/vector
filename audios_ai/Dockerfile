FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for PyTorch and audio
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 50052

CMD ["python", "audios_ai.py"]