from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import google.generativeai as genai
import re
import os
import json
from dotenv import load_dotenv
import cv2
import base64
from PIL import Image
import numpy as np

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# === GEMINI CONFIG ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file")

genai.configure(api_key=GEMINI_API_KEY)
text_model = genai.GenerativeModel('gemini-2.0-flash-exp')   # Updated for text (stable)
vision_model = genai.GenerativeModel('gemini-2.0-flash-exp') # Updated for vision (supports images, fixed 404)

# Debug: List available models on startup
print("Available Gemini models with generateContent support:")
for model in genai.list_models():
    if 'generateContent' in model.supported_generation_methods:
        print(f" - {model.name}")

# === ESP32 CONFIG ===
ESP32_IP = "http://192.168.29.247"  # Change to your ESP32 IP

# === JOINTS STATE ===
JOINTS = {
    "base": {"pin": "D4", "min_angle": -180, "max_angle": 180, "current_angle": 90},
    "shoulder": {"pin": "D1", "min_angle": 0, "max_angle": 170, "current_angle": 90},
    "elbow": {"pin": "D5", "min_angle": 0, "max_angle": 170, "current_angle": 90},
    "wrist": {"pin": "D8", "min_angle": -180, "max_angle": 180, "current_angle": 90},
    "gripper": {"pin": "D0", "open_angle": 180, "closed_angle": 0, "current_state": "open"}
}

# === CAMERA HELPERS ===
def capture_frame():
    """Capture a single frame from webcam."""
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return None
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None

def encode_frame_to_base64(frame):
    """Convert OpenCV frame to base64 string."""
    _, buffer = cv2.imencode('.jpg', frame)
    return base64.b64encode(buffer).decode('utf-8')

def analyze_frame_with_gemini(frame, user_query):
    """Send frame + query to Gemini Vision and get response."""
    try:
        image_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        prompt = f"""
        Analyze this image and answer the user's question naturally.
        If describing objects, say "I can see [object]".
        If not found, say "I cannot see [object]".
        
        User question: {user_query}
        """
        response = vision_model.generate_content([prompt, image_pil])
        return response.text.strip()
    except Exception as e:
        print(f"Vision error details: {str(e)}")  # Log for debugging
        return f"Vision analysis unavailable right now (API issue). Try a text command like 'help'. Error: {str(e)[:100]}..."

# === ROBOTIC ARM PARSERS ===
def parse_command_simple(user_input):
    user_input_lower = user_input.lower()
    if 'emergency' in user_input_lower or 'stop' in user_input_lower:
        return {'joint': 'emergency_stop', 'value': None}
    if 'gripper' in user_input_lower:
        if any(w in user_input_lower for w in ['open', 'release']):
            return {'joint': 'gripper', 'value': 'open'}
        elif any(w in user_input_lower for w in ['close', 'grip', 'grab']):
            return {'joint': 'gripper', 'value': 'closed'}
    for joint in ['base', 'shoulder', 'elbow', 'wrist']:
        if joint in user_input_lower:
            angle_match = re.search(r'(\d+)\s*degrees?', user_input_lower)
            if angle_match:
                return {'joint': joint, 'value': int(angle_match.group(1))}
            elif any(w in user_input_lower for w in ['up', 'increase', 'raise']):
                return {'joint': joint, 'value': JOINTS[joint]['current_angle'] + 30}
            elif any(w in user_input_lower for w in ['down', 'decrease', 'lower']):
                return {'joint': joint, 'value': JOINTS[joint]['current_angle'] - 30}
    return {'joint': 'error', 'value': 'Invalid command. Type "help" for examples.'}

def parse_command(user_input):
    try:
        prompt = f"""
        You are controlling a robotic arm with joints: base, shoulder, elbow, wrist, gripper.
        - Angles: base/wrist (-180..180), shoulder/elbow (0..170)
        - Gripper: 'open' or 'closed'
        - Emergency stop: reset all to default
        
        Parse this into JSON: {{ "joint": "...", "value": ... }}
        If not a valid arm command, return {{ "joint": "error", "value": "..." }}
        
        User: "{user_input}"
        Return ONLY valid JSON.
        """
        response = text_model.generate_content(prompt)
        json_match = re.search(r'\{[^}]*\}', response.text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except:
                pass
        return parse_command_simple(user_input)
    except Exception as e:
        print(f"Text parsing error: {str(e)}")
        return parse_command_simple(user_input)

# === ESP32 COMMUNICATION ===
def send_to_esp32(command_data):
    joint = command_data.get("joint")
    value = command_data.get("value")

    if joint == "error":
        return {"status": "error", "message": value}

    try:
        if joint == "emergency_stop":
            resp = requests.post(f"{ESP32_IP}/api/arm/command", json={"command": "EMERGENCY_STOP"}, timeout=2)
            if resp.status_code == 200:
                for j in ["base", "shoulder", "elbow", "wrist"]:
                    JOINTS[j]["current_angle"] = 90
                JOINTS["gripper"]["current_state"] = "open"
                return {"status": "success", "message": "Emergency stop: all joints reset"}
            return {"status": "error", "message": "ESP32 error"}

        elif joint == "gripper":
            target = value.lower()
            current = JOINTS["gripper"]["current_state"]
            if target == current:
                return {"status": "success", "message": f"Gripper already {target}"}
            resp = requests.post(f"{ESP32_IP}/api/arm/command", json={"command": "GRIPPER_TOGGLE"}, timeout=2)
            if resp.status_code == 200:
                JOINTS["gripper"]["current_state"] = target
                return {"status": "success", "message": f"Gripper {target}"}
            return {"status": "error", "message": "Failed to toggle gripper"}

        else:
            if joint not in JOINTS:
                return {"status": "error", "message": "Invalid joint"}
            try:
                angle = int(value)
                min_a, max_a = JOINTS[joint]["min_angle"], JOINTS[joint]["max_angle"]
                if not (min_a <= angle <= max_a):
                    return {"status": "error", "message": f"Angle must be {min_a}–{max_a}°"}
                current = JOINTS[joint]["current_angle"]
                step = 5
                steps = abs(angle - current) // step
                if steps == 0:
                    return {"status": "success", "message": f"{joint.title()} already at {angle}°"}

                direction = "RIGHT" if angle > current else "LEFT" if joint in ["base", "wrist"] else "DOWN"
                direction = "UP" if angle > current and joint in ["shoulder", "elbow"] else direction
                cmd_map = {"base": "WAIST", "shoulder": "SHOULDER", "elbow": "ELBOW", "wrist": "WRIST"}
                cmd = f"{cmd_map[joint]}_{direction}"

                for _ in range(steps):
                    r = requests.post(f"{ESP32_IP}/api/arm/command", json={"command": cmd}, timeout=2)
                    if r.status_code != 200:
                        return {"status": "error", "message": "ESP32 rejected command"}

                new_angle = current + (step * steps * (1 if "UP" in cmd or "RIGHT" in cmd else -1))
                JOINTS[joint]["current_angle"] = max(min_a, min(max_a, new_angle))
                return {"status": "success", "message": f"Moved {joint} to {JOINTS[joint]['current_angle']}°"}

            except ValueError:
                return {"status": "error", "message": "Invalid angle"}

    except requests.Timeout:
        return {"status": "error", "message": "ESP32 timeout"}
    except requests.ConnectionError:
        return {"status": "error", "message": "Cannot connect to ESP32"}
    except Exception as e:
        return {"status": "error", "message": f"Error: {str(e)}"}

# === HELP & GREETINGS ===
def handle_help_request():
    examples = [
        "move base to 45 degrees", "move shoulder up", "close gripper",
        "emergency stop", "what can you see in the frame"
    ]
    msg = "Robotic Arm Control Commands:\n" + "\n".join(f"• {ex}" for ex in examples)
    return {"status": "success", "message": msg}

def handle_greeting(user_input):
    greetings = {
        "hello": "Hi! I'm your robotic arm assistant. Try 'move base to 90 degrees' or 'what can you see in the frame'!",
        "hi": "Hello! Ready to control the arm? Say 'close gripper' or ask me to see the camera.",
        "how are you": "I'm powered up and ready! Try 'open gripper' or 'what can you see in the frame'."
    }
    key = user_input.lower().strip()
    return {"status": "success", "message": greetings.get(key)} if key in greetings else None

# === ROUTES ===
@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({"response": "Please send a message."}), 400

    user_lower = user_message.lower()

    # === VISION COMMAND: "what can you see in the frame" ===
    if "frame" in user_lower and ("see" in user_lower or "look" in user_lower or "show" in user_lower):
        frame = capture_frame()
        if frame is None:
            return jsonify({
                "response": "Camera not available. Please check connection.",
                "image": None
            }), 500

        ai_response = analyze_frame_with_gemini(frame, user_message)
        image_b64 = encode_frame_to_base64(frame)

        return jsonify({
            "response": ai_response,
            "image": image_b64,
            "requires_camera": False
        })

    # === HELP ===
    if any(k in user_lower for k in ['help', 'what can i do', 'how to']):
        result = handle_help_request()

    # === GREETING ===
    elif handle_greeting(user_message):
        result = handle_greeting(user_message)

    # === ROBOT CONTROL ===
    else:
        parsed = parse_command(user_message)
        if parsed.get("joint") != "error":
            result = send_to_esp32(parsed)
        else:
            result = handle_help_request()

    # Format response
    msg = result.get("message", "Unknown error")
    prefix = "✅ " if result.get("status") == "success" else "❌ "
    return jsonify({"response": prefix + msg})

@app.route('/telemetry', methods=['GET'])
def telemetry():
    try:
        resp = requests.get(f"{ESP32_IP}/api/arm/telemetry", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            for j in ["base", "shoulder", "elbow", "wrist"]:
                JOINTS[j]["current_angle"] = data.get(f"{j}Angle", JOINTS[j]["current_angle"])
            JOINTS["gripper"]["current_state"] = data.get("gripperState", "Open").lower()
            return jsonify(data)
        return jsonify({"error": "Failed to get telemetry"}), 500
    except:
        return jsonify({"error": "ESP32 unreachable"}), 500

if __name__ == '__main__':
    print("Starting Flask server with Updated Vision + Robotic Arm Control...")
    app.run(host='0.0.0.0', port=5000, debug=True)