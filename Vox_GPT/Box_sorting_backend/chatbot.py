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
import time

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# === ESP8266 CONFIG ===
ESP_IP = "http://192.168.29.247"  # Change to your ESP8266 IP

# === ROBOT ARM POSITIONS (for color sorting) ===
pick_position = [135, 40, 90, 15]
white_after_pick_position = [135, 180, 180, 45]
white_position = [105, 135, 150, 90]
blue_after_pick_position = [135, 180, 180, 45]
blue_position = [160, 110, 130, 90]
black_after_pick_position = [135, 90, 140, 45] # Using 'other' for black
black_drop_position = [25, 150, 180, 90]     # Using 'other' for black
initial_position = [125, 180, 90, 90]

# === ARM MOVEMENT VIA HTTP ===
def move_arm_smooth_http(start_pos, end_pos, steps=10, delay=0.1):
    """Smoothly moves the arm by sending a series of HTTP requests."""
    for i in range(steps + 1):
        intermediate_pos = [
            int(start_pos[j] + (end_pos[j] - start_pos[j]) * (i / steps))
            for j in range(4)
        ]
        command = f"{intermediate_pos[0]} {intermediate_pos[1]} {intermediate_pos[2]} {intermediate_pos[3]}"
        try:
            requests.post(f"{ESP_IP}/move", data={"positions": command}, timeout=1)
        except requests.RequestException as e:
            print(f"Error sending command to ESP: {e}")
            # Continue trying even if one step fails
        time.sleep(delay)

def handle_pick_and_place(color):
    """Handles the full sequence for picking and placing a colored box."""
    if color not in ["blue", "white", "black"]:
        return {"status": "error", "message": "I can only pick blue, white, or black boxes."}

    try:
        # 1. Go to pick position and grab
        move_arm_smooth_http(initial_position, pick_position[:3] + [initial_position[3]])
        time.sleep(1)
        move_arm_smooth_http(pick_position[:3] + [initial_position[3]], pick_position) # Close gripper
        time.sleep(1)

        # 2. Move to the correct drop-off sequence based on color
        if color == "white":
            move_arm_smooth_http(pick_position, white_after_pick_position)
            time.sleep(1)
            move_arm_smooth_http(white_after_pick_position, white_position[:3] + [10])
            time.sleep(1)
            move_arm_smooth_http(white_position[:3] + [10], white_position[:3] + [90]) # Open gripper
            time.sleep(1)
            move_arm_smooth_http(white_position[:3] + [90], initial_position)
        
        elif color == "blue":
            move_arm_smooth_http(pick_position, blue_after_pick_position)
            time.sleep(1)
            move_arm_smooth_http(blue_after_pick_position, blue_position[:3] + [10])
            time.sleep(1)
            move_arm_smooth_http(blue_position[:3] + [10], blue_position[:3] + [90]) # Open gripper
            time.sleep(1)
            move_arm_smooth_http(blue_position[:3] + [90], initial_position)

        elif color == "black":
            move_arm_smooth_http(pick_position, black_after_pick_position)
            time.sleep(1)
            move_arm_smooth_http(black_after_pick_position, black_drop_position[:3] + [10])
            time.sleep(1)
            move_arm_smooth_http(black_drop_position[:3] + [10], black_drop_position[:3] + [90]) # Open gripper
            time.sleep(1)
            move_arm_smooth_http(black_drop_position[:3] + [90], initial_position)

        return {"status": "success", "message": f"Sequence for picking the {color} box completed."}

    except Exception as e:
        # Move to initial position in case of any error during sequence
        # Note: This requires knowing the current position or having a safe default
        # For simplicity, we just log the error and return
        print(f"An error occurred during the pick and place sequence: {e}")
        return {"status": "error", "message": f"An error occurred: {e}. The arm may be in an inconsistent state."}


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

# Color detection
def detect_color(roi):
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    # Detect white
    _, thresh_white = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

    # Detect blue
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([100, 150, 50])
    upper_blue = np.array([140, 255, 255])
    mask_blue = cv2.inRange(hsv, lower_blue, upper_blue)

    contours_white, _ = cv2.findContours(thresh_white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours_blue, _ = cv2.findContours(mask_blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    white_detected = any(cv2.contourArea(cnt) > 500 for cnt in contours_white)
    blue_detected = any(cv2.contourArea(cnt) > 500 for cnt in contours_blue)

    if white_detected:
        return "white"
    elif blue_detected:
        return "blue"
    else:
        return "other"

def analyze_frame_locally(frame, user_query):
    """Analyzes the frame locally to detect color, bypassing the Gemini API."""
    h, w, _ = frame.shape
    square_size = 100
    x1, y1 = (w // 2 - square_size // 2, h // 2 - square_size // 2)
    x2, y2 = (w // 2 + square_size // 2, h // 2 + square_size // 2)
    roi = frame[y1:y2, x1:x2]

    detected = detect_color(roi)

    if detected == "white":
        return "I can see a white object."
    elif detected == "blue":
        return "I can see a blue object."
    else:
        # Check for black/dark objects
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        avg_intensity = np.mean(gray_roi)
        if avg_intensity < 50:
            return "I can see a black object."
        return "I don't see a blue, white, or black object in the center."


# === LEGACY ROBOTIC ARM PARSERS (Disabled) ===
def parse_command_simple(user_input):
    return {'joint': 'error', 'value': 'This command is not supported by the current controller.'}

def parse_command(user_input):
    return {'joint': 'error', 'value': 'This command is not supported by the current controller.'}

# === LEGACY ESP32 COMMUNICATION (Disabled) ===
def send_to_esp32(command_data):
    return {"status": "error", "message": "This function is disabled for the current controller."}

# === HELP & GREETINGS ===
def handle_help_request():
    examples = [
        "pick the blue box",
        "pick the white box",
        "pick the black box",
        "what can you see in the frame"
    ]
    msg = "You can try the following commands:\n" + "\n".join(f"• {ex}" for ex in examples)
    return {"status": "success", "message": msg}

def handle_greeting(user_input):
    greetings = {
        "hello": "Hi! I'm your robotic arm assistant. Try 'pick the blue box' or ask 'what can you see?'.",
        "hi": "Hello! Ready to sort some boxes? Say 'pick the white box'.",
        "how are you": "I'm powered up and ready for sorting!"
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
    result = None

    # === PICK AND PLACE COMMAND ===
    pick_match = re.search(r'pick(?: up| the)?\s+(blue|white|black)\s+box', user_lower)
    if pick_match:
        color = pick_match.group(1)
        result = handle_pick_and_place(color)

    # === VISION COMMAND ===
    elif "frame" in user_lower and ("see" in user_lower or "look" in user_lower or "show" in user_lower):
        frame = capture_frame()
        if frame is None:
            return jsonify({"response": "Camera not available. Please check connection.", "image": None}), 500
        
        ai_response = analyze_frame_locally(frame, user_message)
        image_b64 = encode_frame_to_base64(frame)
        return jsonify({"response": ai_response, "image": image_b64, "requires_camera": False})

    # === HELP & GREETINGS ===
    elif any(k in user_lower for k in ['help', 'what can i do', 'how to']):
        result = handle_help_request()
    elif handle_greeting(user_message):
        result = handle_greeting(user_message)

    # === FALLBACK / UNKNOWN COMMAND ===
    else:
        result = {"status": "error", "message": "Sorry, I didn't understand that. Try 'help' to see what I can do."}

    # Format and send response
    prefix = "✅ " if result.get("status") == "success" else "❌ "
    return jsonify({"response": prefix + result.get("message", "An unknown error occurred.")})

@app.route('/telemetry', methods=['GET'])
def telemetry():
    # This endpoint is unlikely to work as the new ESP code doesn't have it.
    return jsonify({"error": "Telemetry is not available with the current controller."}), 503

if __name__ == '__main__':
    print("Starting Flask server with Updated Vision + Robotic Arm Control...")
    app.run(host='0.0.0.0', port=5000, debug=True)