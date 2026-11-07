"""Speech-to-text: Groq Whisper Large v3 Turbo, Gemini, or Sarvam AI."""

from __future__ import annotations

import sys
import os
import logging
from pathlib import Path
from typing import Optional, Union
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

logger = logging.getLogger(__name__)

STT_PROVIDER = os.environ.get("STT_PROVIDER", "auto")  # "groq" | "gemini" | "sarvam" | "auto"


def transcribe(audio_input_data: Union[bytes, str, Path], mime_type: str = "audio/wav") -> str:
    """Transcribe audio to text with automatic provider selection and fallbacks.
    
    Accepts:
    - File path (str or Path) to an audio file (.wav, .webm, .ogg, .mp3, .m4a, etc.)
    - Raw audio bytes
    """
    original_filename = ""
    audio_bytes = b""

    # 1. Handle file path input
    if isinstance(audio_input_data, (str, Path)):
        filepath = Path(str(audio_input_data))
        if not filepath.exists():
            print(f"[STT] Error: File path does not exist: {filepath}")
            return ""
        original_filename = filepath.name
        ext = filepath.suffix.lstrip(".").lower()
        if ext in ("wav", "webm", "ogg", "mp3", "m4a", "flac"):
            mime_type = f"audio/{ext}"
        try:
            with open(filepath, "rb") as f:
                audio_bytes = f.read()
        except Exception as e:
            print(f"[STT] Error reading audio file {filepath}: {e}")
            return ""

    elif isinstance(audio_input_data, bytes):
        audio_bytes = audio_input_data

    else:
        print(f"[STT] Invalid audio input type: {type(audio_input_data)}")
        return ""

    if not audio_bytes or len(audio_bytes) < 200:
        print(f"[STT] Audio is empty or too short: {len(audio_bytes)} bytes.")
        return ""

    provider = os.environ.get("STT_PROVIDER", "groq").lower()

    # 1. Prefer Groq Whisper when GROQ_API_KEY is available
    if os.environ.get("GROQ_API_KEY"):
        res = _transcribe_groq(audio_bytes, mime_type=mime_type, original_filename=original_filename)
        if res:
            return res

    # 2. Sarvam AI if configured and requested
    if provider == "sarvam" and os.environ.get("SARVAM_API_KEY"):
        res = _transcribe_sarvam(audio_bytes, mime_type)
        if res:
            return res

    # 3. Gemini if GEMINI_API_KEY is present
    if os.environ.get("GEMINI_API_KEY"):
        try:
            res = _transcribe_gemini(audio_bytes, mime_type)
            if res:
                return res
        except Exception as e:
            logger.warning(f"Gemini STT failed: {e}")

    # Fallback to Sarvam AI if configured
    if os.environ.get("SARVAM_API_KEY"):
        return _transcribe_sarvam(audio_bytes, mime_type)

    print("[STT] No speech-to-text API keys found (GROQ_API_KEY, GEMINI_API_KEY, or SARVAM_API_KEY).")
    return ""


def _transcribe_groq(audio_bytes: bytes, mime_type: str = "audio/wav", original_filename: str = "") -> str:
    """Use Groq's whisper-large-v3-turbo for fast multilingual speech-to-text."""
    import requests
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("[STT] GROQ_API_KEY is missing.")
        return ""

    # Determine extension and filename
    ext = "wav"
    if original_filename and "." in original_filename:
        ext = original_filename.rsplit(".", 1)[-1].lower()
    elif "/" in mime_type:
        ext = mime_type.split("/")[-1].lower()

    if ext in ("wave", "x-wav"):
        ext = "wav"
    elif ext in ("mpeg", "mp3"):
        ext = "mp3"
    elif ext in ("m4a", "mp4"):
        ext = "m4a"
    elif ext in ("webm",):
        ext = "webm"
    elif ext in ("ogg",):
        ext = "ogg"

    filename = f"voice_input.{ext}"
    files = {
        "file": (filename, audio_bytes, f"audio/{ext}"),
    }
    # No forced language constraint: enables automatic multilingual detection for Hindi, Hinglish, English, Tamil, etc.
    data = {
        "model": "whisper-large-v3-turbo",
        "response_format": "json",
    }
    headers = {
        "Authorization": f"Bearer {api_key}"
    }

    try:
        print(f"[STT] Transcribing {len(audio_bytes)} bytes as {filename} via Groq Whisper...")
        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers=headers,
            files=files,
            data=data,
            timeout=30,
        )
        print(f"[STT] Groq Whisper HTTP status: {resp.status_code}")
        if resp.status_code == 200:
            transcript = resp.json().get("text", "").strip()
            try:
                safe_log = transcript[:120].encode("ascii", errors="replace").decode("ascii")
                print(f"[STT] Successfully transcribed ({len(transcript)} chars): {safe_log}")
            except Exception:
                pass
            return transcript
        else:
            print(f"[STT] Groq Whisper error {resp.status_code}: {resp.text[:200]}")
            return ""
    except Exception as e:
        try:
            print(f"[STT] Groq Whisper request exception: {str(e).encode('ascii', errors='replace').decode('ascii')}")
        except Exception:
            pass
        return ""


def _transcribe_gemini(audio_bytes: bytes, mime_type: str) -> str:
    """Use Gemini's native audio understanding to transcribe."""
    try:
        from llm import chat_with_audio

        result = chat_with_audio(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Transcribe the following audio exactly as spoken. "
                        "The speaker may be using Hindi, Hinglish (Hindi+English in Latin script), "
                        "English, Tamil, Bengali, Marathi, or another Indian language. "
                        "Output ONLY the transcription, nothing else."
                    ),
                }
            ],
            audio_data=audio_bytes,
            audio_mime=mime_type,
            temperature=0.1,
        )
        return result.strip()
    except Exception as e:
        print(f"[STT] Gemini audio transcription error: {e}")
        return ""


def _transcribe_sarvam(audio_bytes: bytes, mime_type: str) -> str:
    """Use Sarvam AI STT API for Indian language transcription."""
    import requests
    import base64

    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        return ""

    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")

    try:
        response = requests.post(
            "https://api.sarvam.ai/speech-to-text",
            headers={
                "API-Subscription-Key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "input": b64_audio,
                "audio_format": mime_type.split("/")[-1],
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("transcript", "")
    except Exception as e:
        print(f"[STT] Sarvam STT failed: {e}")
        return ""
