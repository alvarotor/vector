import grpc
import audio_pb2
import audio_pb2_grpc
import os
import io
import sys
import tempfile
from concurrent import futures
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
# Simple TTS using Piper (offline)
# Simple TTS using Piper binary (offline)
TTS_AVAILABLE = True
print("Piper binary available")

# Download required voices if not present
import subprocess
voices = ["en_US-lessac-medium", "es_ES-sharvard-medium"]
for voice in voices:
    model_path = f'/root/.local/share/piper/{voice}.onnx'
    if not os.path.exists(model_path):
        print(f"Downloading voice: {voice}")
        try:
            subprocess.run(["piper/piper", "--model", voice, "--output_file", "/tmp/test.wav"], input=b"test", check=True, timeout=60)
            print(f"Downloaded voice: {voice}")
        except subprocess.TimeoutExpired:
            print(f"Timeout downloading {voice}")
        except subprocess.CalledProcessError:
            print(f"Failed to download {voice}")
    else:
        print(f"Voice {voice} already available")

# Audio processing setup
try:
    from pydub import AudioSegment
    from pydub.silence import detect_nonsilent

    PYDUB_AVAILABLE = True
    print("pydub loaded successfully")
except ImportError:
    print("pydub not available, silence removal will be skipped")
    PYDUB_AVAILABLE = False

print("Imports done")

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://user:password@localhost:5432/db"
)

# Move db code inside functions to avoid module level connection issues


print("Script started")
sys.stdout.flush()

# Simple TTS setup
tts_available = TTS_AVAILABLE


class AudioServicer(audio_pb2_grpc.AudioServiceServicer):
    def GenerateAudioFromText(self, request, context):
        print(f"GenerateAudioFromText called with text: {request.text[:50]}")
        print(f"Voice: {request.voice}, format: {request.format}, language: {request.language}")
        try:
            if not TTS_AVAILABLE:
                raise Exception("Piper TTS not available")

            # Select model based on voice or language
            if request.voice:
                model_name = request.voice
            elif request.language == "es":
                model_name = "es_ES-sharvard-medium"
            else:
                model_name = "tts_models/en/vctk/vits"

            import subprocess

            # Use Piper
            model = request.voice or "en_US-lessac-medium"
            text = request.text

            suffix = '.wav'
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                temp_path = temp_file.name

            model_path = f'/root/.local/share/piper/{model}.onnx'
            config_path = f'/root/.local/share/piper/{model}.onnx.json'
            cmd = ['piper/piper', '-m', model_path, '-c', config_path, '-f', temp_path]
            subprocess.run(cmd, input=text.encode('utf-8'), check=True)

            with open(temp_path, 'rb') as f:
                wav_bytes = f.read()

            os.unlink(temp_path)
            print(f"Generated {len(wav_bytes)} bytes with voice {model}")
            audio_bytes = wav_bytes
            format_type = "wav"

            print(f"Generated audio length: {len(audio_bytes)} bytes")

        except Exception as e:
            print(f"Audio generation failed: {e}")
            import traceback

            traceback.print_exc()
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Audio generation failed")
            return audio_pb2.GenerateAudioResponse()

        return audio_pb2.GenerateAudioResponse(
            audio_data=audio_bytes, format=format_type, sample_rate=22050
        )

    def GenerateAudioFromId(self, request, context):
        print(f"GenerateAudioFromId called with id: {request.id}")
        try:
            return self._generate_audio_from_id(request, context)
        except Exception as e:
            print(f"Unexpected error in GenerateAudioFromId: {e}")
            import traceback

            traceback.print_exc()
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Unexpected error")
            return audio_pb2.GenerateAudioResponse()

    def _generate_audio_from_id(self, request, context):
        if not tts_available:
            print("TTS not available")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("TTS not available")
            return audio_pb2.GenerateAudioResponse()

        # Get text from database using id
        id = request.id
        text = None
        try:
            print(f"Looking up text with id: {id}")
            engine = create_engine(DATABASE_URL)
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            db = SessionLocal()
            Base = declarative_base()

            class TextEntry(Base):
                __tablename__ = "texts"
                id = Column(String, primary_key=True, index=True)
                text = Column(Text, nullable=False)

            entry = db.query(TextEntry).filter(TextEntry.id == id).first()
            if not entry:
                print(f"Text with id {id} not found")
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details("Text not found")
                return audio_pb2.GenerateAudioResponse()
            text = entry.text
            print(f"Found text: {text[:100]}...")
            db.close()
        except Exception as e:
            print(f"Database error: {e}")
            import traceback

            traceback.print_exc()
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Database error")
            return audio_pb2.GenerateAudioResponse()

        format_type = request.format or "mp3"
        language = request.language or "en"
        voice = request.voice or None
        if format_type not in ["mp3", "wav"]:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Unsupported format")
            return audio_pb2.GenerateAudioResponse()

        # Generate audio using Piper
        print(f"Generating audio for ID: {id}, text: {text[:50]} in {language} with voice {voice}...")
        try:
            # Clean and prepare text
            text = text.strip()  # Remove leading/trailing whitespace
            if not text:
                raise Exception("Empty text after cleaning")

            if not TTS_AVAILABLE:
                raise Exception("Piper TTS not available")

            # Select model based on voice or language
            if voice:
                model_name = voice
            elif language == "es":
                model_name = "es_ES-sharvard-medium"
            else:
                model_name = "tts_models/en/vctk/vits"

            import subprocess

            # Use Piper
            model = voice or "en_US-lessac-medium"

            suffix = '.wav'
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                temp_path = temp_file.name

            model_path = f'/root/.local/share/piper/{model}.onnx'
            config_path = f'/root/.local/share/piper/{model}.onnx.json'
            cmd = ['piper/piper', '-m', model_path, '-c', config_path, '-f', temp_path]
            subprocess.run(cmd, input=text.encode('utf-8'), check=True)

            with open(temp_path, 'rb') as f:
                wav_bytes = f.read()

            os.unlink(temp_path)
            print(f"Generated {len(wav_bytes)} bytes with voice {model}")
            audio_bytes = wav_bytes
            format_type = "wav"

            print(f"Generated audio length: {len(audio_bytes)} bytes")

            # Piper audio is clean, but optionally trim silence if needed
            if PYDUB_AVAILABLE:
                try:
                    # Convert bytes to AudioSegment
                    audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format=format_type)

                    # Detect non-silent chunks
                    chunks = detect_nonsilent(
                        audio_segment,
                        min_silence_len=300,  # 300ms minimum silence
                        silence_thresh=-35,
                    )  # -35 dBFS threshold

                    if chunks:
                        # Get the start of the first non-silent chunk
                        start_trim = chunks[0][0]
                        # Keep some buffer (50ms) before the actual speech
                        start_trim = max(0, start_trim - 50)

                        # Trim from the beginning
                        trimmed_audio = audio_segment[start_trim:]

                        # Convert back to bytes
                        output_buffer = io.BytesIO()
                        trimmed_audio.export(output_buffer, format=format_type)
                        audio_bytes = output_buffer.getvalue()

                        print(
                            f"Trimmed audio length: {len(audio_bytes)} bytes (removed {start_trim}ms of silence)"
                        )

                except Exception as e:
                    print(f"Silence removal failed: {e}, using original audio")
            else:
                print("pydub not available, skipping silence removal")

        except Exception as e:
            print(f"Audio generation failed: {e}")
            import traceback

            traceback.print_exc()
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Audio generation failed")
            return audio_pb2.GenerateAudioResponse()

        return audio_pb2.GenerateAudioResponse(
            audio_data=audio_bytes, format=format_type, sample_rate=22050
        )


# Removed _to_bytes method - gTTS already outputs bytes


def serve():
    print("Starting gRPC server on port 50052")
    sys.stdout.flush()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    servicer = AudioServicer()
    print("Servicer created:", type(servicer))
    print("Has GenerateAudioFromId:", hasattr(servicer, "GenerateAudioFromId"))
    print("Method object:", getattr(servicer, "GenerateAudioFromId", None))
    sys.stdout.flush()
    # Manually add generic handler
    rpc_method_handlers = {
        "GenerateAudioFromText": grpc.unary_unary_rpc_method_handler(
            servicer.GenerateAudioFromText,
            request_deserializer=audio_pb2.GenerateAudioFromTextRequest.FromString,
            response_serializer=audio_pb2.GenerateAudioResponse.SerializeToString,
        ),
        "GenerateAudioFromId": grpc.unary_unary_rpc_method_handler(
            servicer.GenerateAudioFromId,
            request_deserializer=audio_pb2.GenerateAudioFromIdRequest.FromString,
            response_serializer=audio_pb2.GenerateAudioResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        "AudioService", rpc_method_handlers
    )
    server.add_generic_rpc_handlers((generic_handler,))
    print("Generic handler added")
    server.add_insecure_port("0.0.0.0:50052")
    server.start()
    print("gRPC server started")
    sys.stdout.flush()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
