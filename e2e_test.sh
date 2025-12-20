#!/bin/bash

# Check input
if [ -z "$1" ]; then
  echo "Usage: $0 <text>"
  exit 1
fi

TEXT="$1"
ESCAPED_TEXT=$(echo "$TEXT" | sed 's/"/\\"/g')  # Basic escaping
ENCODED_QUERY=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$ESCAPED_TEXT'''))")

BASE_URL="http://localhost:8000"

# Clean up previous data
echo "Cleaning up previous data..."
curl -s -X DELETE "$BASE_URL/delete_all_texts" > /dev/null

# Step 1: Add text
echo "Adding text: $TEXT"
RESPONSE=$(curl -s -X POST "$BASE_URL/add_text" -H "Content-Type: application/json" -d "{\"text\": \"$ESCAPED_TEXT\"}")
ID=$(echo "$RESPONSE" | jq -r '.id')
if [ "$ID" == "null" ] || [ -z "$ID" ]; then
  echo "Failed to add text: $RESPONSE"
  exit 1
fi
echo "Added text with ID: $ID"

# Step 2: Search
echo "Searching for text..."
SEARCH_RESPONSE=$(curl -s "$BASE_URL/search_literal?query=$ENCODED_QUERY")
COUNT=$(echo "$SEARCH_RESPONSE" | jq -r 'length' 2>/dev/null || echo "0")
if [ "$COUNT" != "1" ]; then
  echo "Search failed: Expected 1 result, got $COUNT"
  exit 1
fi
echo "Found 1 instance as expected"

# Step 3: Generate audio in 3 voices
VOICES=("en_US-lessac-medium" "en_US-ryan-medium" "en_US-amy-medium")
for VOICE in "${VOICES[@]}"; do
  echo "Generating audio with voice: $VOICE"
  curl -s -X POST "$BASE_URL/generate_audio_from_id" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$ID\", \"format\": \"mp3\", \"language\": \"en\", \"voice\": \"$VOICE\"}" \
    -o "audio_$VOICE.mp3"
  if [ ! -s "audio_$VOICE.mp3" ]; then
    echo "Failed to download audio for $VOICE"
  else
    FILE_SIZE=$(stat -f%z "audio_$VOICE.mp3" 2>/dev/null || stat -c%s "audio_$VOICE.mp3" 2>/dev/null || echo "0")
    echo "Downloaded audio_$VOICE.mp3 ($FILE_SIZE bytes)"
  fi
done

# Step 4: Upload and transcribe
echo "Uploading and transcribing audio_en_US-lessac-medium.mp3"
UPLOAD_RESPONSE=$(curl -s -X POST "$BASE_URL/transcribe_audio" -F "file=@audio_en_US-lessac-medium.mp3" -F "language=en")
NEW_ID=$(echo "$UPLOAD_RESPONSE" | jq -r '.text_id')
if [ "$NEW_ID" == "null" ] || [ -z "$NEW_ID" ]; then
  echo "Transcription failed: $UPLOAD_RESPONSE"
  exit 1
fi
echo "Transcription created new text ID: $NEW_ID"

# Step 5: Final search
echo "Final search for text..."
FINAL_SEARCH=$(curl -s "$BASE_URL/search_literal?query=$ENCODED_QUERY")
FINAL_COUNT=$(echo "$FINAL_SEARCH" | jq -r 'length' 2>/dev/null || echo "0")
if [ "$FINAL_COUNT" != "2" ]; then
  echo "Test FAILED: Expected 2 results, got $FINAL_COUNT"
  echo "Results: $FINAL_SEARCH"
  exit 1
fi
echo "Test PASSED: Text appears twice"
echo "Original ID: $ID"
echo "Transcribed ID: $NEW_ID"

# Optional cleanup
# rm audio_*.mp3