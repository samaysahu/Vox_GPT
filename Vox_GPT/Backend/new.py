import threading
import time
import math
from PIL import Image
import numpy as np
import cv2
from dotenv import load_dotenv
import json
import os
import re
import google.generativeai as genai
import requests
from flask_cors import CORS
from flask import Flask, request, jsonify

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# === GEMINI CONFIG ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file")

genai.configure(api_key=GEMINI_API_KEY)
text_model = genai.GenerativeModel('gemini-pro')
vision_model = genai.GenerativeModel('gemini-pro-vision')

# === ESP32 CONFIG ===
ESP32_IP = "http://10.44.37.80"  # Change to your ESP32 IP

# === ROBOT ARM DIMENSIONS (in cm) ===
BASE_HEIGHT = 7.0
HUMERUS_LENGTH = 19.0  # Shoulder to Elbow
ULNA_LENGTH = 15.0     # Elbow to Wrist

# === STATE VARIABLES ===
JOINTS = {
    "base": {"pin": "D4", "min_angle": 0, "max_angle": 180, "current_angle": 90},
    "shoulder": {"pin": "D1", "min_angle": 0, "max_angle": 170, "current_angle": 90},
    "elbow": {"pin": "D5", "min_angle": 0, "max_angle": 170, "current_angle": 90},
    "wrist": {"pin": "D8", "min_angle": 0, "max_angle": 180, "current_angle": 90},
    "gripper": {"pin": "D0", "open_angle": 120, "closed_angle": 0, "current_state": "open"}
}
HOME_POSITION_ANGLES = {"base": 10, "shoulder": 70, "elbow": 160, "wrist": 120}
LAST_COMMAND_DETAILS = None
IS_REPEATING = False

# Global variables for saved poses
saved_poses = {}
next_pose_id = 1

# === KINEMATICS ===
def calculate_inverse_kinematics(x, y, z):
    try:
        base_angle_rad = math.atan2(y, x)
        base_angle_deg = int(math.degrees(base_angle_rad))
        servo_base_angle = 90 - base_angle_deg
        servo_base_angle = max(JOINTS["base"]["min_angle"], min(JOINTS["base"]["max_angle"], servo_base_angle))

        r = math.sqrt(x**2 + y**2)
        z_prime = z - BASE_HEIGHT
        d = math.sqrt(r**2 + z_prime**2)

        if d > (HUMERUS_LENGTH + ULNA_LENGTH) or d < abs(HUMERUS_LENGTH - ULNA_LENGTH):
            return {"error": "Target is unreachable."}

        alpha1 = math.acos((HUMERUS_LENGTH**2 + d**2 - ULNA_LENGTH**2) / (2 * HUMERUS_LENGTH * d))
        alpha2 = math.atan2(z_prime, r)
        servo_shoulder_angle = int(math.degrees(alpha1 + alpha2))
        servo_shoulder_angle = max(JOINTS["shoulder"]["min_angle"], min(JOINTS["shoulder"]["max_angle"], servo_shoulder_angle))

        beta = math.acos((HUMERUS_LENGTH**2 + ULNA_LENGTH**2 - d**2) / (2 * HUMERUS_LENGTH * ULNA_LENGTH))
        servo_elbow_angle = 180 - int(math.degrees(math.pi - beta))
        servo_elbow_angle = max(JOINTS["elbow"]["min_angle"], min(JOINTS["elbow"]["max_angle"], servo_elbow_angle))

        return {"base": servo_base_angle, "shoulder": servo_shoulder_angle, "elbow": servo_elbow_angle}
    except (ValueError, ZeroDivisionError):
        return {"error": "Calculation error. The target might be out of the arm's work envelope."}

# === BACKGROUND REPEAT THREAD ===
def _repeat_movement_thread():
    global IS_REPEATING, LAST_COMMAND_DETAILS, HOME_POSITION_ANGLES
    print("Repeat thread started.")
    while IS_REPEATING:
        if not LAST_COMMAND_DETAILS or not IS_REPEATING: break
        
        # Extract coordinates from LAST_COMMAND_DETAILS
        coords = LAST_COMMAND_DETAILS['coords']

        # --- Go to Home Position ---
        home_angles_payload = {"command": "SET_ANGLES", **HOME_POSITION_ANGLES}
        send_command_to_esp32(home_angles_payload)
        time.sleep(3) # Wait for arm to reach home position (3 seconds)
        if not IS_REPEATING: break

        # --- Go to Last Coordinate ---
        angles = calculate_inverse_kinematics(coords['x'], coords['y'], coords['z'])
        if "error" not in angles:
            send_command_to_esp32({"command": "SET_ANGLES", **angles})
            time.sleep(1) # Wait for arm to reach target position (1 second)
        else:
            print(f"Error reaching last coordinate in repeat: {angles['error']}")
            IS_REPEATING = False
        
        time.sleep(1) # Small delay before next cycle
    print("Repeat thread finished.")

# === CAMERA HELPERS ===
def capture_frame():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened(): return None
    ret, frame = cap.read(); cap.release()
    return frame if ret else None

def encode_frame_to_base64(frame):
    _, buffer = cv2.imencode('.jpg', frame)
    return base64.b64encode(buffer).decode('utf-8')

def analyze_frame_with_gemini(frame, user_query):
    try:
        image_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        response = vision_model.generate_content([f"Analyze this image: {user_query}", image_pil])
        return response.text.strip()
    except Exception as e:
        return f"Vision analysis unavailable. Error: {str(e)[:100]}..."

# === ROBOT ARM PARSERS ===
def parse_move_to_command(user_input):
    pattern = r"move\s+(?:arm\s+to\s+)?x\s*=\s*(-?\d+(?:\.\d+)?)\s*,\s*y\s*=\s*(-?\d+(?:\.\d+)?)\s*,\s*z\s*=\s*(-?\d+(?:\.\d+)?)\s*(?:(?:,|\s)\s*(?:g|gripper)\s+(open|close))?"
    match = re.search(pattern, user_input, re.IGNORECASE)
    if match:
        coords = {"x": float(match.group(1)), "y": float(match.group(2)), "z": float(match.group(3))}
        gripper_state = match.group(4)
        return {"type": "move_to", "coords": coords, "gripper_state": gripper_state}
    return None

def parse_angle_command(user_input):
    pattern = r"move\s+(base|shoulder|elbow|wrist)\s+to\s+(\d+)\s*degrees?"
    match = re.search(pattern, user_input, re.IGNORECASE)
    if match:
        return {"joint": match.group(1).lower(), "value": int(match.group(2))}
    return None

def parse_jog_command(user_input):
    """Parses 'jog [axis] by [value]' commands."""
    pattern = r"(?:jog|move|nudge)\s+(x|y|z)\s+by\s+(-?\d+(?:\.\d+)?)"
    match = re.search(pattern, user_input, re.IGNORECASE)
    if match:
        axis = match.group(1).lower()
        value = float(match.group(2))
        return {"axis": axis, "value": value}
    return None

def parse_gripper_state_command(user_input):
    """Parses 'open gripper' or 'close gripper' commands."""
    pattern = r"(open|close)\s+gripper"
    match = re.search(pattern, user_input, re.IGNORECASE)
    if match:
        return {"state": match.group(1).lower()}
    return None

# === ESP32 COMMUNICATION ===
def send_command_to_esp32(payload):
    global JOINTS
    try:
        url = f"{ESP32_IP}/api/arm/command"
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            # Update local joint states if SET_ANGLES command was successful
            if payload.get("command") == "SET_ANGLES":
                for joint_name in ["base", "shoulder", "elbow", "wrist"]:
                    if joint_name in payload:
                        JOINTS[joint_name]["current_angle"] = payload[joint_name]
            return {"status": "success", "message": response.json().get("status", "Done")}
        return {"status": "error", "message": f"ESP32 returned status {response.status_code}"}
    except requests.RequestException as e:
        print(f"ERROR: Cannot connect to ESP32 at {url}. Details: {e}")
        return {"status": "error", "message": f"Cannot connect to ESP32: {e}"}

# === HELP & GREETINGS ===
def handle_help_request():
    examples = [
        "move arm to x=20, y=0, z=25, g open",
        "jog x by 5",
        "move y by -10",
        "move base to 45 degrees",
        "move to home",
        "repeat",
        "stop",
        "close gripper",
    ]
    return {"status": "success", "message": "You can try:\n" + "\n".join(f"• {ex}" for ex in examples)}

def handle_greeting(user_input):
    """Handles simple greetings."""
    greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]
    if any(greeting in user_input.lower() for greeting in greetings):
        return {"status": "success", "message": "Hello! How can I help you with the arm today?"}
    return None

# === ROUTES ===
@app.route('/chat', methods=['POST'])
def chat():
    global IS_REPEATING, LAST_COMMAND_DETAILS, saved_poses, next_pose_id, saved_poses, next_pose_id
    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({"response": "Please send a message."} ), 400

    user_lower = user_message.lower()
    result = None

    # --- Command Processing Order ---
    if 'stop' in user_lower or 'emergency' in user_lower:
        if IS_REPEATING:
            IS_REPEATING = False
            result = {"status": "success", "message": "Repetition stopped."}
        else:
            result = send_command_to_esp32({"command": "EMERGENCY_STOP"})
    elif 'home' in user_lower:
        payload = {"command": "SET_ANGLES", **HOME_POSITION_ANGLES, "gripper": "open"}
        result = send_command_to_esp32(payload)
    elif 'repeat' in user_lower:
        if LAST_COMMAND_DETAILS is None:
            result = {"status": "error", "message": "No last command to repeat."}
        elif IS_REPEATING:
            result = {"status": "info", "message": "Already in repeat mode."}
        else:
            IS_REPEATING = True
            threading.Thread(target=_repeat_movement_thread, daemon=True).start()
            result = {"status": "success", "message": "Starting repeat cycle. Say 'stop' to end."}
    elif user_lower == "save":
        if LAST_COMMAND_DETAILS and LAST_COMMAND_DETAILS.get("type") == "move_to":
            pose_id = next_pose_id
            saved_poses[pose_id] = LAST_COMMAND_DETAILS.copy()
            next_pose_id += 1
            result = {"status": "success", "message": f"Pose saved with ID: {pose_id}"}
        else:
            result = {"status": "error", "message": "No arm position to save. Please move the arm to a specific coordinate first."}
    elif user_lower.startswith("move to id"):
        try:
            parts = user_lower.split()
            pose_id = int(parts[3])
            if pose_id in saved_poses:
                saved_pose = saved_poses[pose_id]
                coords = saved_pose["coords"]
                gripper_state_from_saved_pose = saved_pose.get("gripper_state")

                angles = calculate_inverse_kinematics(coords["x"], coords["y"], coords["z"])
                if "error" in angles:
                    result = {"status": "error", "message": angles["error"]}
                else:
                    LAST_COMMAND_DETAILS = saved_pose # Update LAST_COMMAND_DETAILS
                    payload = {"command": "SET_ANGLES", **angles}
                    result = send_command_to_esp32(payload) # Send angle command first

                    if result.get("status") == "success" and gripper_state_from_saved_pose:
                        time.sleep(1) # Wait for 1 second after angle movement
                        gripper_payload = {"command": "GRIPPER_TOGGLE", "gripper": gripper_state_from_saved_pose}
                        result = send_command_to_esp32(gripper_payload) # Then send gripper command
                    
                    if result.get("status") == "success":
                        result["message"] = f"Moving arm to saved pose ID {pose_id} (X={coords['x']}, Y={coords['y']}, Z={coords['z']}, Gripper={gripper_state_from_saved_pose or 'unchanged'})."
            else:
                result = {"status": "error", "message": f"Pose with ID {pose_id} not found."}
        except (IndexError, ValueError):
            result = {"status": "error", "message": "Invalid 'move to id' command format. Please use: move to id X"}
    else:
        move_to_cmd = parse_move_to_command(user_message)
        angle_cmd = parse_angle_command(user_message)
        jog_cmd = parse_jog_command(user_message)

        if move_to_cmd:
            coords = move_to_cmd["coords"]
            angles = calculate_inverse_kinematics(coords["x"], coords["y"], coords["z"])
            if "error" in angles:
                result = {"status": "error", "message": angles["error"]}
            else:
                LAST_COMMAND_DETAILS = move_to_cmd
                payload = {"command": "SET_ANGLES", **angles}
                gripper_state_from_cmd = move_to_cmd.get("gripper_state")
                gripper_state_to_send = None
                if gripper_state_from_cmd:
                    gripper_state_to_send = gripper_state_from_cmd.lower()
                
                result = send_command_to_esp32(payload) # Send angle command first
                
                if gripper_state_to_send:
                    time.sleep(1) # Wait for 1 second after angle movement
                    gripper_payload = {"command": "GRIPPER_TOGGLE", "gripper": gripper_state_to_send}
                    result = send_command_to_esp32(gripper_payload) # Then send gripper command
        
        elif jog_cmd:
            if LAST_COMMAND_DETAILS is None:
                result = {"status": "error", "message": "Cannot jog. Please move to an absolute position first."}
            else:
                # Extract coords from LAST_COMMAND_DETAILS
                current_coords = LAST_COMMAND_DETAILS['coords'].copy()
                new_coords = current_coords.copy()
                new_coords[jog_cmd["axis"]] += jog_cmd["value"]
                angles = calculate_inverse_kinematics(new_coords["x"], new_coords["y"], new_coords["z"])
                if "error" in angles:
                    result = {"status": "error", "message": f"Jog move is unreachable: {angles['error']}"}
                else:
                    # Update LAST_COMMAND_DETAILS with new coordinates
                    LAST_COMMAND_DETAILS['coords'] = new_coords
                    payload = {"command": "SET_ANGLES", **angles}
                    result = send_command_to_esp32(payload)

        elif angle_cmd:
            joint, target_angle = angle_cmd["joint"], angle_cmd["value"]
            
            # Create a payload with current angles for all joints, then update the commanded joint
            payload_angles = {}
            for j_name, j_data in JOINTS.items():
                if j_name in ["base", "shoulder", "elbow", "wrist"]:
                    payload_angles[j_name] = j_data["current_angle"]
            
            payload_angles[joint] = target_angle # Override the commanded joint's angle

            min_a, max_a = JOINTS[joint]["min_angle"], JOINTS[joint]["max_angle"]
            if not (min_a <= target_angle <= max_a):
                result = {"status": "error", "message": f"For {joint}, angle must be between {min_a} and {max_a}°."}
            else:
                payload = {"command": "SET_ANGLES", **payload_angles}
                result = send_command_to_esp32(payload)

        elif "frame" in user_lower and "see" in user_lower:
            frame = capture_frame()
            if frame is None: return jsonify({"response": "Camera not available."} ), 500
            return jsonify({"response": analyze_frame_with_gemini(frame, user_message), "image": encode_frame_to_base64(frame)})
        
        elif 'help' in user_lower:
            result = handle_help_request()
        
        elif handle_greeting(user_message):
             result = handle_greeting(user_message)
        
        else:
            result = handle_help_request()

    # --- Gripper commands ---
    gripper_state_cmd = parse_gripper_state_command(user_message)
    if gripper_state_cmd:
        result = send_command_to_esp32({"command": "GRIPPER_TOGGLE", "gripper": gripper_state_cmd["state"]})
    elif 'gripper' in user_lower:
        result = send_command_to_esp32({"command": "GRIPPER_TOGGLE"})

    if result and result.get("status") == "success" and not result.get("message"):
        result["message"] = "Done."

    prefix = "✅ " if result.get("status") == "success" else "❌ " if result.get("status") == "error" else "ℹ️ "
    return jsonify({"response": prefix + result.get("message", "An unknown error occurred.")})

@app.route('/telemetry', methods=['GET'])
def telemetry():
    try:
        resp = requests.get(f"{ESP32_IP}/api/arm/telemetry", timeout=3)
        if resp.status_code == 200:
            return jsonify(resp.json())
        return jsonify({"error": "Failed to get telemetry"}), 500
    except:
        return jsonify({"error": "ESP32 unreachable"}), 500

if __name__ == '__main__':
    print("Starting Flask server with Jogging support...")
    app.run(host='0.0.0.0', port=5000, debug=True)
