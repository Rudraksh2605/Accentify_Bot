from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from gtts import gTTS
import google.generativeai as genai
import langid
import os
import re
import uuid
from datetime import datetime, timedelta
import shutil

# App configuration
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure Gemini
genai.configure(api_key=os.getenv("AIzaSyDwEyFoPIr9nDJcUeM-Gn0qsR635IhXcu8"))
model = genai.GenerativeModel("gemini-1.5-pro")

# Constants
AUDIO_DIR = "audio_files"
MAX_AUDIO_FILES = 100  # Maximum number of audio files to keep
AUDIO_RETENTION_HOURS = 24  # Hours to keep audio files

# Ensure audio directory exists
os.makedirs(AUDIO_DIR, exist_ok=True)

def cleanup_old_audio():
    """Remove old audio files to prevent storage buildup"""
    now = datetime.now()
    for filename in os.listdir(AUDIO_DIR):
        file_path = os.path.join(AUDIO_DIR, filename)
        file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
        if now - file_time > timedelta(hours=AUDIO_RETENTION_HOURS):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")

def detect_language(text):
    """Detect if text is German or English with enhanced checks"""
    text_lower = text.lower()
    lang, confidence = langid.classify(text)

    # Enhanced German detection
    german_indicators = sum([
        any(c in text_lower for c in ['ä', 'ö', 'ü', 'ß']),
        len({'ich', 'du', 'wir', 'sein'} & set(text_lower.split())) > 1,
        confidence > 0.8 and lang == 'de'
    ])

    return 'de' if german_indicators >= 2 else 'en'

def parse_response(response_text):
    """Parse Gemini response into translation and example"""
    patterns = [
        r'Translation:\s*([^\n]+)\nExample:\s*([^(]+)\(([^)]+)',  # Strict format
        r'([^\n]+)\n([^(]+)\(([^)]+)',                           # No labels
        r'Translation:\s*([^\n]+).*?Example:\s*([^(]+)\(([^)]+)' # Multiline
    ]

    for pattern in patterns:
        match = re.search(pattern, response_text, re.DOTALL | re.IGNORECASE)
        if match:
            translation = match.group(1).strip()
            example_target = match.group(2).strip()
            example_english = match.group(3).strip()
            return translation, f"{example_target} ({example_english})"

    raise ValueError(f"Response parsing failed for: {response_text[:150]}...")

@app.route('/chat', methods=['POST'])
def chat():
    """Handle translation requests"""
    try:
        data = request.get_json()
        user_text = data.get("text", "").strip()

        if not user_text:
            return jsonify({"error": "Empty input"}), 400

        # Clean up old files before processing new request
        cleanup_old_audio()

        source_lang = detect_language(user_text)
        target_lang = 'de' if source_lang == 'en' else 'en'
        lang_pair = f"{source_lang.upper()}-{target_lang.upper()}"

        audio_id = uuid.uuid4().hex
        audio_path = os.path.join(AUDIO_DIR, f"{audio_id}.mp3")

        prompt = f"""**{lang_pair} Translation Request**
        Input: "{user_text}"

        - Provide ONLY:
          1. Direct translation
          2. {target_lang.upper()} example sentence
          3. English translation of example in parentheses

        **Example Response:**
        Translation: {'Hallo' if target_lang == 'de' else 'Hello'}
        Example: {'Hallo, wie geht es Ihnen? (Hello, how are you?)' if target_lang == 'de' else 'Hello, how are you? (Hallo, wie geht es Ihnen?)'}"""

        response = model.generate_content(prompt)
        translation, example = parse_response(response.text)

        if translation.lower() == user_text.lower():
            raise ValueError("Translation matches input")

        if target_lang == 'de' and not re.search(r'[äöüß]', translation, re.IGNORECASE):
            print(f"Warning: German translation may lack special characters - {translation}")

        example_target = example.split('(')[0].strip()
        tts = gTTS(text=example_target, lang=target_lang)
        tts.save(audio_path)

        return jsonify({
            "original": user_text,
            "translation": translation,
            "example": example,
            "audio_url": f"/audio/{audio_id}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/audio/<audio_id>')
def serve_audio(audio_id):
    """Serve audio files with validation"""
    if not re.match(r'^[a-f0-9]{32}$', audio_id):
        return jsonify({"error": "Invalid audio ID"}), 400
        
    audio_path = os.path.join(AUDIO_DIR, f"{audio_id}.mp3")
    if os.path.exists(audio_path):
        return send_file(audio_path)
    return jsonify({"error": "Audio not found"}), 404

@app.route('/health')
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        "status": "healthy",
        "audio_files": len(os.listdir(AUDIO_DIR))
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
