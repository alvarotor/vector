Plan to Replace gTTS with Offline TTS
Based on code analysis, replacing gTTS (which requires internet for every TTS request) with an offline alternative is moderate difficulty—straightforward but requires code changes, testing, and dependency updates. Here's the plan:
Difficulty Assessment
- Effort Level: 2-3 hours for implementation + testing (beginner-friendly Python changes).
- Risk: Low—existing error handling covers failures; rollback to gTTS possible.
- Tradeoffs: 
  - Quality: gTTS is natural (Google-quality); offline options like pyttsx3 are good but OS-dependent (better on Windows/macOS than Linux).
  - Features: gTTS supports global languages; pyttsx3 is English-focused but extensible.
  - Performance: pyttsx3 is faster (local synthesis); no internet latency.
Recommended Solution: pyttsx3
- Why? Fully offline, cross-platform, easy install, decent quality. Outputs to files (adaptable to bytes like current code).
- Alternatives Considered: Coqui TTS (best quality but complex/heavy); eSpeak (lightweight but robotic).
Step-by-Step Plan
1. Update Dependencies (5 min):
   - Edit audios_ai/requirements.txt: Remove gtts, add pyttsx3.
   - Update audios_ai/Dockerfile:### Plan to Replace gTTS with Offline TTS
Goal: Eliminate internet dependency for text-to-speech by replacing gTTS with an offline alternative, enabling full offline operation.
Difficulty Assessment: Moderate (2-3 hours for implementation + testing). The change is straightforward—minimal code modifications needed—but requires testing across platforms for audio quality. No breaking changes to gRPC API; core logic remains intact.
Recommended Alternative: pyttsx3 (balances ease, quality, and compatibility). It's lightweight, offline-capable, and outputs MP3/WAV via OS-native engines. If you prefer higher quality (neural voices), Coqui TTS is an option but adds complexity (PyTorch deps, model downloads).
Steps to Implement
1. Update Dependencies (5 min)
   - Edit audios_ai/requirements.txt: Remove gtts, add pyttsx3.
   - Edit audios_ai/Dockerfile: Ensure pyttsx3 is installed (already handled by requirements.txt). Add system TTS engines if needed (e.g., RUN apt-get install espeak-ng for Linux).
2. Modify Code in audios_ai/audios_ai.py (30-45 min)
   - Replace imports: Remove from gtts import gTTS, add import pyttsx3.
   - Update availability check: Change to try: import pyttsx3; TTS_AVAILABLE = True with fallback.
   - Rewrite audio generation logic (in GenerateAudioFromText and _generate_audio_from_id):
     - Use pyttsx3.init() instead of gTTS.
     - Output to a temporary file (pyttsx3 doesn't support direct bytes), then read into audio_bytes.
     - Set properties: rate ~180 for natural speed, voice to 'english' (OS-dependent).
     - Retain error handling, silence trimming, and format/sample rate logic.
   - Example code snippet (replace gTTS block):
          import tempfile
     import os
     engine = pyttsx3.init()
     engine.setProperty('rate', 180)
     engine.setProperty('voice', 'english')
     with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
         temp_path = temp_file.name
     try:
         engine.save_to_file(text, temp_path)
         engine.runAndWait()
         with open(temp_path, 'rb') as f:
             audio_bytes = f.read()
     finally:
         os.unlink(temp_path)
        - For WAV format: Change suffix to .wav and use pydub for conversion if needed.
3. Test Implementation (45-60 min)
   - Unit Tests: Generate short texts, verify non-empty audio bytes and formats.
   - Integration Tests: Full gRPC calls, database flow, playback for quality.
   - Cross-Platform: Test on Linux/Windows/macOS (quality varies; Docker ensures consistency).
   - Edge Cases: Long texts, errors, silence trimming.
   - Performance: Compare generation time (pyttsx3 is faster).
4. Build and Deploy (10 min)
   - Rebuild Docker image: docker-compose build audios_ai.
   - Verify offline: Run services without internet, test TTS requests.
Risks & Mitigations:
- Audio quality: pyttsx3 is OS-dependent (best on macOS/Windows); test and document.
- Compatibility: No direct bytes output—temp files add minimal overhead.
- Fallback: Keep gTTS import optional for easy rollback.
Estimated Effort: 2-4 hours total. Ready to implement once you approve—any preferences (e.g., Coqui TTS instead)?