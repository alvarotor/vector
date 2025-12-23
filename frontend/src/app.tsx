/// <reference types="vite/client" />
import { useState, useEffect, useRef } from 'preact/hooks';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';

export function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [conversation, setConversation] = useState<string[]>([]);
  const [sessionId, setSessionId] = useState<string>('');
  const [mediaRecorder, setMediaRecorder] = useState<MediaRecorder | null>(null);
  const conversationRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const storedSession = localStorage.getItem('sessionId');
    if (storedSession) {
      setSessionId(storedSession);
      const storedConversation = localStorage.getItem('chatHistory');
      if (storedConversation) {
        try {
          setConversation(JSON.parse(storedConversation));
        } catch (e) {
          console.error('Error loading conversation:', e);
        }
      }
    } else {
      const newSession = Math.random().toString(36).substring(2);
      setSessionId(newSession);
      localStorage.setItem('sessionId', newSession);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem('chatHistory', JSON.stringify(conversation));
    // Auto-scroll to bottom
    setTimeout(() => {
      if (conversationRef.current) {
        conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
      }
    }, 0);
  }, [conversation]);

  const startRecording = async () => {
    const recordStart = performance.now();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      setMediaRecorder(recorder);
      const chunks: Blob[] = [];

      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        const recordDuration = (performance.now() - recordStart) / 1000;
        const blob = new Blob(chunks, { type: 'audio/wav' });
        console.log(`Recording stopped: ${recordDuration.toFixed(2)}s duration, blob size: ${(blob.size / 1024).toFixed(2)}KB`);
        await processAudio(blob);
        stream.getTracks().forEach(track => track.stop());
      };

      recorder.start();
      setIsRecording(true);
      setConversation(prev => [...prev, 'Listening...']);
    } catch (err) {
      console.error('Error starting recording:', err);
      setConversation(prev => [...prev, 'Error: Could not access microphone']);
    }
  };

  const stopRecording = () => {
    if (mediaRecorder) {
      mediaRecorder.stop();
      setIsRecording(false);
    }
  };

  const processAudio = async (inputBlob: Blob) => {
    try {
      // Transcribe
      const transcribeStart = performance.now();
      const formData = new FormData();
      formData.append('file', inputBlob, 'audio.wav');
      const transcribeRes = await fetch(`${BACKEND_URL}/transcribe_audio`, {
        method: 'POST',
        body: formData,
      });
      if (!transcribeRes.ok) throw new Error('Transcription failed');
      const transcribeData = await transcribeRes.json();
      const transcribed = transcribeData.transcription;
      const transcribeTime = (performance.now() - transcribeStart) / 1000;
      console.log(`Transcribe API: ${transcribeTime.toFixed(2)}s`);
      setConversation(prev => [...prev, `You: ${transcribed}`]);

      // Generate response
      const responseStart = performance.now();
      const responseRes = await fetch(`${BACKEND_URL}/generate_response`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: transcribed, session_id: sessionId, lang: transcribeData.detected_language }),
      });
      if (!responseRes.ok) throw new Error('Response generation failed');
      const responseData = await responseRes.json();
      const aiResponse = responseData.response;
      const responseTime = (performance.now() - responseStart) / 1000;
      console.log(`Generate Response API: ${responseTime.toFixed(2)}s`);
      setConversation(prev => [...prev, `AI: ${aiResponse}`]);

      // Generate and play audio
      const audioStart = performance.now();
      const audioRes = await fetch(`${BACKEND_URL}/generate_audio_from_text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: aiResponse, format: 'wav', language: transcribeData.detected_language }),
      });
      if (!audioRes.ok) throw new Error('Audio generation failed');
      const audioBlob = await audioRes.blob();
      const audioTime = (performance.now() - audioStart) / 1000;
      console.log(`Generate Audio API: ${audioTime.toFixed(2)}s`);
      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);
      audio.play();
    } catch (err) {
      console.error('Error processing audio:', err);
      setConversation(prev => [...prev, 'Error: Processing failed']);
    }
  };

  return (
    <div>
      <h1>Voice Chat</h1>
       <button onClick={startRecording} disabled={isRecording}>Start Listening</button>
       <button onClick={stopRecording} disabled={!isRecording}>Stop & Send</button>
        <textarea
          id="conversation"
          ref={conversationRef}
          value={conversation.join('\n\n')}
          readOnly
          rows={20}
          style={{ width: '100%', resize: 'none' }}
        />
    </div>
  );
}