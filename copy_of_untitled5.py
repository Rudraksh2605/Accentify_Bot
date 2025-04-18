from flask import Flask, request, jsonify, send_file
from gtts import gTTS
import google.generativeai as genai
import langid
import os
import re
import uuid

# Configure Gemini
genai.configure(api_key="YOUR_GEMINI_API_KEY_HERE")
model = genai.GenerativeModel("gemini-1.5-pro")

# App setup
app = Flask(__name__)
AUDIO_DIR = "audio_files"
os.makedirs(AUDIO_DIR, exist_ok=True)

def detect_language(text):
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
    try:
        data = request.get_json()
        user_text = data.get("text", "").strip()

        if not user_text:
            return jsonify({"error": "Empty input"}), 400

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
            "audio_url": f"/audio/{audio_id}"  # Only path, not full URL
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/audio/<audio_id>')
def serve_audio(audio_id):
    audio_path = os.path.join(AUDIO_DIR, f"{audio_id}.mp3")
    if os.path.exists(audio_path):
        return send_file(audio_path)
    else:
        return jsonify({"error": "Audio not found"}), 404

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)

