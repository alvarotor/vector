FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for PyTorch and audio
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    git \
    espeak-ng \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip uninstall protobuf -y || true
RUN pip install --upgrade --force-reinstall protobuf==4.21.12

COPY . .

# Download Piper binary
RUN wget https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_arm64.tar.gz && tar -xzf piper_arm64.tar.gz && rm piper_arm64.tar.gz
RUN chmod +x piper/piper

# Models will be downloaded on first use and cached

# PB2 files already generated

EXPOSE 50052

CMD ["python", "audios_ai.py"]
# Pre-download Piper models
RUN mkdir -p /root/.local/share/piper && \
    wget -O /root/.local/share/piper/en_US-lessac-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx && \
    wget -O /root/.local/share/piper/en_US-lessac-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json && \
    wget -O /root/.local/share/piper/en_US-ryan-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx && \
    wget -O /root/.local/share/piper/en_US-ryan-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx.json && \
    wget -O /root/.local/share/piper/en_US-amy-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx && \
    wget -O /root/.local/share/piper/en_US-amy-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json

