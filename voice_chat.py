#!/usr/bin/env python3
import speech_recognition as sr
import pyaudio
import wave
import io
import requests
import time
import tempfile
import os
import uuid
from pynput.keyboard import Key, Listener
from pydub import AudioSegment

interrupt_flag = False

# API endpoints (assuming backend on localhost:8000)
BACKEND_URL = "http://localhost:8000"

# Session management
session_file = "session.txt"
try:
    with open(session_file, "r") as f:
        session_id = f.read().strip()
except FileNotFoundError:
    session_id = str(uuid.uuid4())
    with open(session_file, "w") as f:
        f.write(session_id)

def record_audio(mic_index):
    """Record audio until silence or spacebar press"""
    record_start = time.time()
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.0  # 1 second silence to stop
    with sr.Microphone(device_index=mic_index) as source:
        print("Listening... Speak or press spacebar.")
        audio = recognizer.listen(source)
    record_duration = time.time() - record_start
    print(f"Recording completed in {record_duration:.2f}s")
    return audio

def transcribe_audio(audio):
    """Send audio to transcribe endpoint"""
    # Save audio to temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        temp_file_name = temp_file.name
        audio_data = audio.get_wav_data()
        temp_file.write(audio_data)
    wav_size = len(audio_data)
    print(f"Audio prepared: {wav_size} bytes")

    transcribe_start = time.time()
    with open(temp_file_name, "rb") as f:
        files = {"file": ("audio.wav", f, "audio/wav")}
        data = {"session_id": session_id}
        headers = {"User-Agent": "voice_chat.py"}
        response = requests.post(f"{BACKEND_URL}/transcribe_audio", files=files, data=data, headers=headers)
    transcribe_time = time.time() - transcribe_start
    print(f"Transcribe API call: {transcribe_time:.2f}s")

    os.unlink(temp_file_name)

    if response.status_code == 200:
        data = response.json()
        return data["transcription"], data.get("effective_language", "en")
    else:
        print(f"Transcription failed: {response.text}")
        return None, "en"

def generate_response(text, lang="en"):
    """Send text to LLM for response"""
    payload = {"text": text, "session_id": session_id, "lang": lang}
    response_start = time.time()
    response = requests.post(f"{BACKEND_URL}/generate_response", json=payload)
    response_time = time.time() - response_start
    print(f"Generate Response API call: {response_time:.2f}s")
    if response.status_code == 200:
        data = response.json()
        return data["response"]
    else:
        print(f"Response generation failed: {response.text}")
        return None

def generate_audio(text, lang="en"):
    """Send text to TTS with voice based on language, fallback to English if fails"""
    voices = ["es_ES-sharvard-medium" if lang == "es" else "en_US-lessac-medium", "en_US-lessac-medium"]
    audio_start = time.time()
    for voice in voices:
        payload = {"text": text, "format": "wav", "voice": voice}
        response = requests.post(f"{BACKEND_URL}/generate_audio_from_text", json=payload)
        if response.status_code == 200:
            audio_time = time.time() - audio_start
            print(f"Generate Audio API call: {audio_time:.2f}s")
            return response.content
        else:
            print(f"Audio generation failed with {voice}: {response.text}")
    return None

def on_press(key):
    global interrupt_flag
    if key == Key.space:
        interrupt_flag = True
        return False  # Stop listener

def play_audio(audio_data):
    """Play WAV audio data with interrupt on spacebar"""
    global interrupt_flag
    if audio_data:
        interrupt_flag = False
        listener = Listener(on_press=on_press)
        listener.start()

        wf = wave.open(io.BytesIO(audio_data), 'rb')
        p = pyaudio.PyAudio()
        stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                        channels=wf.getnchannels(),
                        rate=wf.getframerate(),
                        output=True)
        data = wf.readframes(1024)
        while data:
            stream.write(data)
            if interrupt_flag:
                print("Playback interrupted by spacebar.")
                break
            data = wf.readframes(1024)
        stream.stop_stream()
        stream.close()
        p.terminate()
        listener.stop()

def main():
    mic_list = sr.Microphone.list_microphone_names()
    mic_index = None
    if mic_list:
        print(f"Available microphones: {[f'{i}: {name}' for i, name in enumerate(mic_list)]}")
        # Force MacBook Pro microphone
        for i, name in enumerate(mic_list):
            if "MacBook Pro" in name or "Built-in Microphone" in name:
                mic_index = i
                print(f"Forcing microphone: {name}")
                break
        if mic_index is None:
            print("MacBook Pro mic not found. Please choose a microphone by number:")
            try:
                choice = int(input("Enter microphone index: "))
                if 0 <= choice < len(mic_list):
                    mic_index = choice
                    print(f"Selected: {mic_list[mic_index]}")
                else:
                    mic_index = 0
                    print(f"Invalid choice, using default: {mic_list[0]}")
            except ValueError:
                mic_index = 0
                print(f"Invalid input, using default: {mic_list[0]}")
    else:
        print("No microphones found.")

    print(f"Voice Chat Started. Session ID: {session_id}. Press Ctrl+C to quit.")
    while True:
        try:
            audio = record_audio(mic_index)
            if audio:
                transcribed, detected_lang = transcribe_audio(audio)
                if transcribed:
                    print(f"You: {transcribed}")
                    response_text = generate_response(transcribed, detected_lang)
                    if response_text:
                        print(f"AI: {response_text}")
                        audio_data = generate_audio(response_text, detected_lang)
                        if audio_data:
                            play_audio(audio_data)
        except KeyboardInterrupt:
            print("\nExiting voice chat.")
            break

if __name__ == "__main__":
    main()