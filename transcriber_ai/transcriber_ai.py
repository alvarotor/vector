import grpc
import transcribe_pb2
import transcribe_pb2_grpc
import os
import io
import sys
import time
import tempfile
from concurrent import futures

# Whisper for transcription
import whisper
import torch
import numpy as np
from pydub import AudioSegment
import ffmpeg

print("Imports done")

MODEL_NAME = os.environ.get("MODEL_NAME", "base")

MODEL_DEVICE = os.environ.get("MODEL_DEVICE", "auto")

# Global model cache
whisper_model = None


def load_whisper_model():
    """Load Whisper model on demand"""
    global whisper_model
    if whisper_model is None:
        print("Loading Whisper model (this may take a moment)...")
        start_time = time.time()

        if MODEL_DEVICE == "auto":

            device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")

        else:

            device = MODEL_DEVICE

        print(f"Using device: {device}")

        # Load model for speed (can be configured to medium/large)

        whisper_model = whisper.load_model(MODEL_NAME, device=device)

        load_time = time.time() - start_time
        print(".2f")
    return whisper_model


def preprocess_audio(audio_bytes, format_type):
    """Convert audio bytes to format suitable for Whisper"""
    try:
        # Load audio with pydub
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes))

        # Convert to mono if stereo
        if audio_segment.channels > 1:
            audio_segment = audio_segment.set_channels(1)

        # Convert to 16kHz sample rate (Whisper requirement)
        if audio_segment.frame_rate != 16000:
            audio_segment = audio_segment.set_frame_rate(16000)

        # Export as WAV bytes for Whisper
        wav_buffer = io.BytesIO()
        audio_segment.export(wav_buffer, format="wav")
        wav_buffer.seek(0)
        wav_bytes = wav_buffer.read()

        return wav_bytes

    except Exception as e:
        print(f"Audio preprocessing failed: {e}")
        raise


class TranscriberServicer(transcribe_pb2_grpc.TranscriberServiceServicer):
    def TranscribeAudio(self, request, context):
        audio_size = len(request.audio_data)
        print(
            f"TranscribeAudio called - format: {request.format}, language: {request.language or 'auto'}, audio size: {audio_size} bytes"
        )

        start_time = time.time()

        try:
            # Load Whisper model
            preprocess_start = time.time()
            model = load_whisper_model()
            load_time = time.time() - preprocess_start
            print(f"Model loaded in {load_time:.2f}s")

            # Preprocess audio
            print("Preprocessing audio...")
            wav_bytes = preprocess_audio(request.audio_data, request.format)
            preprocess_time = time.time() - preprocess_start - load_time
            print(f"Preprocessing completed in {preprocess_time:.2f}s, wav size: {len(wav_bytes)} bytes")

            # Save to temporary file for Whisper
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_file.write(wav_bytes)
                temp_file_path = temp_file.name

            try:
                # Load audio as numpy array from file
                audio_array = whisper.load_audio(temp_file_path)
            finally:
                # Clean up temp file
                os.unlink(temp_file_path)
            audio_array = whisper.pad_or_trim(audio_array)

            # Create mel spectrogram
            inference_start = time.time()
            mel = whisper.log_mel_spectrogram(audio_array).to(model.device)

            # Detect language if not specified
            if not request.language:
                print("Detecting language...")
                _, probs = model.detect_language(mel)
                detected_lang = max(probs, key=probs.get)
                max_prob = probs[detected_lang]
                print(f"Detected language: {detected_lang} (confidence: {max_prob:.3f})")
                print(f"All probs: {probs}")
                # Fallback to English if not English/Spanish or low confidence
                if detected_lang not in ["en", "es"] or max_prob < 0.6:
                    detected_lang = "en"
                    print("Fallback to English due to unsupported language or low confidence")
            else:
                detected_lang = request.language

            # Transcribe
            print(f"Transcribing audio as {detected_lang}...")
            device = model.device
            print(f"Using device: {device}")
            options = whisper.DecodingOptions(

                language=detected_lang if detected_lang != "auto" else None,

                fp16=device != "cpu",

            )

            result = whisper.decode(model, mel, options)
            inference_time = time.time() - inference_start
            print(f"Whisper inference completed in {inference_time:.2f}s on {device}")

            processing_time = time.time() - start_time

            # Extract transcription and confidence
            transcription = result.text.strip()
            confidence = (
                float(result.avg_logprob) if hasattr(result, "avg_logprob") else 0.0
            )

            print(".2f")
            print(
                f"Transcription: {transcription[:100]}{'...' if len(transcription) > 100 else ''}"
            )
            print(f"Breakdown - Load: {load_time:.2f}s, Preprocess: {preprocess_time:.2f}s, Inference: {inference_time:.2f}s")

            return transcribe_pb2.TranscribeAudioResponse(
                text=transcription,
                detected_language=detected_lang,
                confidence=max(0.0, min(1.0, confidence)),  # Clamp to 0-1 range
                processing_time=processing_time,
            )

        except Exception as e:
            processing_time = time.time() - start_time
            print(f"Transcription failed after {processing_time:.2f}s: {e}")
            import traceback

            traceback.print_exc()

            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Transcription failed: {str(e)}")
            return transcribe_pb2.TranscribeAudioResponse()


# Pre-load model at startup
print("Pre-loading Whisper model at startup...")
try:
    whisper_model = load_whisper_model()
    print("Model pre-loaded successfully")
except Exception as e:
    print(f"Failed to pre-load model: {e}")
    whisper_model = None


def serve():
    print("Starting gRPC transcriber server on port 50053")
    sys.stdout.flush()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    servicer = TranscriberServicer()
    transcribe_pb2_grpc.add_TranscriberServiceServicer_to_server(servicer, server)
    server.add_insecure_port("[::]:50053")
    server.start()

    print("Transcriber gRPC server started successfully")
    sys.stdout.flush()

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("Server stopped")
        server.stop(0)


if __name__ == "__main__":
    serve()