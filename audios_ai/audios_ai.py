import grpc
import audio_pb2
import audio_pb2_grpc
import os
import io
import sys
from concurrent import futures
from sqlalchemy import create_engine, Column, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
# Removed torch/torchaudio imports - using gTTS instead

# Simple TTS using gTTS (Google Text-to-Speech)
try:
    from gtts import gTTS

    TTS_AVAILABLE = True
    print("gTTS loaded successfully")
except ImportError:
    print("gTTS not available, audio generation will not work")
    TTS_AVAILABLE = False

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
    "DATABASE_URL", "postgresql://user:password@postgres:5432/db"
)

# Move db code inside functions to avoid module level connection issues


print("Script started")
sys.stdout.flush()

# Simple TTS setup
tts_available = TTS_AVAILABLE


class AudioServicer(audio_pb2_grpc.AudioServiceServicer):
    def GenerateAudioFromText(self, request, context):
        if not tts_available:
            print("TTS not available")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("TTS not available")
            return audio_pb2.GenerateAudioResponse()

        text = request.text
        format_type = request.format or "mp3"
        if format_type not in ["mp3", "wav"]:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Unsupported format")
            return audio_pb2.GenerateAudioResponse()

        # Generate audio using gTTS
        print(f"Generating audio for text: {text[:50]}...")
        try:
            # Use gTTS to generate audio
            if not TTS_AVAILABLE:
                raise Exception("gTTS not available")
            tts = gTTS(text=text, lang="en", slow=False)
            audio_buffer = io.BytesIO()
            tts.write_to_fp(audio_buffer)
            audio_buffer.seek(0)
            audio_bytes = audio_buffer.read()

            print(f"Generated audio length: {len(audio_bytes)} bytes")

        except Exception as e:
            print(f"Audio generation failed: {e}")
            import traceback

            traceback.print_exc()
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("Audio generation failed")
            return audio_pb2.GenerateAudioResponse()

        return audio_pb2.GenerateAudioResponse(
            audio_data=audio_bytes, format=format_type, sample_rate=24000
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
        if format_type not in ["mp3", "wav"]:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Unsupported format")
            return audio_pb2.GenerateAudioResponse()

        # Generate audio using gTTS
        print(f"Generating audio for ID: {id}, text: {text[:50]}...")
        try:
            # Clean and prepare text
            text = text.strip()  # Remove leading/trailing whitespace
            if not text:
                raise Exception("Empty text after cleaning")

            # Use gTTS to generate audio
            if not TTS_AVAILABLE:
                raise Exception("gTTS not available")
            tts = gTTS(text=text, lang="en", slow=False)
            audio_buffer = io.BytesIO()
            tts.write_to_fp(audio_buffer)
            audio_buffer.seek(0)
            audio_bytes = audio_buffer.read()

            print(f"Generated audio length: {len(audio_bytes)} bytes")

            # Try to remove silence from the beginning (basic approach)
            # gTTS often adds silence at the start, let's try to trim it
            if PYDUB_AVAILABLE:
                try:
                    # Convert bytes to AudioSegment
                    audio_segment = AudioSegment.from_mp3(io.BytesIO(audio_bytes))

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
                        trimmed_audio.export(output_buffer, format="mp3")
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
            audio_data=audio_bytes, format=format_type, sample_rate=24000
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
