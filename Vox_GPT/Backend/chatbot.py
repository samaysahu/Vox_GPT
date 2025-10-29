from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import google.generativeai as genai
import re
import os
import json
from dotenv import load_dotenv

app = Flask(__name__)
CORS(app)

# Load environment variables from .env file
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini API
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# ESP32 IP address (replace with your ESP32's IP after connecting to WiFi)
ESP32_IP = "http://192.168.29.247"  # Update with the actual IP address of your ESP32

# Supported joints and their properties
JOINTS = {
    "base": {"pin": "D4", "min_angle": -180, "max_angle": 180, "current_angle": 90},
    "shoulder": {"pin": "D1", "min_angle": 0, "max_angle": 170, "current_angle": 90},
    "elbow": {"pin": "D5", "min_angle": 0, "max_angle": 170, "current_angle": 90},
    "wrist": {"pin": "D8", "min_angle": -180, "max_angle": 180, "current_angle": 90},
    "gripper": {"pin": "D0", "open_angle": 180, "closed_angle": 0, "current_state": "open"}
}

def parse_command_simple(user_input):
    """Fallback parser using regex patterns for when Gemini is unavailable."""
    user_input_lower = user_input.lower()
    
    # Emergency stop
    if 'emergency' in user_input_lower or 'stop' in user_input_lower:
        return {'joint': 'emergency_stop', 'value': None}
    
    # Gripper commands
    if 'gripper' in user_input_lower:
        if 'open' in user_input_lower or 'release' in user_input_lower:
            return {'joint': 'gripper', 'value': 'open'}
        elif 'close' in user_input_lower or 'grip' in user_input_lower or 'grab' in user_input_lower:
            return {'joint': 'gripper', 'value': 'closed'}
    
    # Angle-based commands
    for joint in ['base', 'shoulder', 'elbow', 'wrist']:
        if joint in user_input_lower:
            # Extract number
            angle_match = re.search(r'(\d+)\s*degrees?', user_input_lower)
            if angle_match:
                angle = int(angle_match.group(1))
                return {'joint': joint, 'value': angle}
            # Check for relative commands
            elif 'up' in user_input_lower or 'increase' in user_input_lower or 'raise' in user_input_lower:
                return {'joint': joint, 'value': JOINTS[joint]['current_angle'] + 30}
            elif 'down' in user_input_lower or 'decrease' in user_input_lower or 'lower' in user_input_lower:
                return {'joint': joint, 'value': JOINTS[joint]['current_angle'] - 30}
    
    return {'joint': 'error', 'value': 'This chatbot is for controlling the robotic arm. Try commands like: move base to 45 degrees, close gripper, or emergency stop.'}

def parse_command(user_input):
    """Use Gemini API to parse natural language commands into structured commands."""
    try:
        prompt = f"""
You are controlling a robotic arm with the following components: base, shoulder, elbow, wrist, and gripper.
        - Base, shoulder, elbow, and wrist can move to specific angles (in degrees).
        - Base and wrist range: -180 to 180 degrees.
        - Shoulder and elbow range: 0 to 170 degrees.
        - Gripper can be 'open' or 'closed'.
        - The command may also include 'emergency stop' to reset all joints to default (90 degrees, gripper open).
        
        Parse the following user command into a JSON object with 'joint' (base, shoulder, elbow, wrist, gripper, or emergency_stop) and 'value' (angle in degrees or 'open'/'closed' for gripper).
        If the command is ambiguous, invalid, or unrelated to robotic arm control, return {{'joint': 'error', 'value': 'This chatbot is for controlling the robotic arm. Try commands like: move base to 45 degrees, close gripper, or emergency stop.'}}.
        Examples:
        - Input: "move base to 40 degrees" -> {{'joint': 'base', 'value': 40}}
        - Input: "close gripper" -> {{'joint': 'gripper', 'value': 'closed'}}
        - Input: "emergency stop" -> {{'joint': 'emergency_stop', 'value': null}}
        - Input: "what is my name" -> {{'joint': 'error', 'value': 'This chatbot is for controlling the robotic arm. Try commands like: move base to 45 degrees, close gripper, or emergency stop.'}}
        - Input: "hello" -> {{'joint': 'error', 'value': 'This chatbot is for controlling the robotic arm. Try commands like: move base to 45 degrees, close gripper, or emergency stop.'}}
        
        User command: "{user_input}"
        
        Return ONLY the JSON object, nothing else.
        """
        response = model.generate_content(prompt)
        
        json_pattern = r'\{[^}]*"joint"[^}]*\}'
        match = re.search(json_pattern, response.text)
        if match:
            try:
                json_str = match.group(0).replace("'", '"')
                parsed = json.loads(json_str)
                return parsed
            except json.JSONDecodeError:
                joint_match = re.search(r'"joint"\s*:\s*"(\w+)"', response.text)
                value_match = re.search(r'"value"\s*:\s*([^,}]+)', response.text)
                if joint_match:
                    joint = joint_match.group(1)
                    value = value_match.group(1).strip().strip('"\'') if value_match else None
                    if value:
                        try:
                            value = int(value)
                        except ValueError:
                            try:
                                value = float(value)
                            except ValueError:
                                pass
                    elif joint == 'emergency_stop':
                        value = None
                    return {'joint': joint, 'value': value}
                return {'joint': 'error', 'value': 'This chatbot is for controlling the robotic arm. Try commands like: move base to 45 degrees, close gripper, or emergency stop.'}
        else:
            return {'joint': 'error', 'value': 'This chatbot is for controlling the robotic arm. Try commands like: move base to 45 degrees, close gripper, or emergency stop.'}
    except Exception as e:
        return parse_command_simple(user_input)

def handle_help_request():
    """Return example commands for controlling the robotic arm."""
    example_commands = [
        "move base to 45 degrees",
        "move shoulder to 90 degrees",
        "move elbow to 120 degrees",
        "move wrist to -30 degrees",
        "open gripper",
        "close gripper",
        "emergency stop"
    ]
    help_message = (
        "This chatbot is designed to control a robotic arm. Try these example commands:\n" +
        "\n".join(f"- {cmd}" for cmd in example_commands) +
        "\n\nJoints (base, wrist) range: -180 to 180 degrees. Shoulder, elbow range: 0 to 170 degrees."
    )
    return {"status": "success", "message": help_message}

def handle_greeting(user_input):
    """Return friendly responses for basic greetings."""
    user_input_lower = user_input.lower().strip()
    greetings = {
        "hello": "Hello! I'm here to control your robotic arm. Try a command like 'move base to 45 degrees' or type 'help' for more examples.",
        "hi": "Hi there! Ready to move the robotic arm? Try 'close gripper' or 'move shoulder to 90 degrees' to get started!",
        "how are you": "I'm doing great, thanks for asking! I'm all set to control your robotic arm. Try 'open gripper' or 'emergency stop' to see me in action!"
    }
    for greeting, response in greetings.items():
        if user_input_lower == greeting:
            return {"status": "success", "message": response}
    return None  # Return None if not a recognized greeting

def send_to_esp32(command_data):
    """Send parsed command to ESP32 and update local state."""
    joint = command_data.get("joint")
    value = command_data.get("value")
    
    if joint == "error":
        return {"status": "error", "message": value}
    
    try:
        if joint == "emergency_stop":
            try:
                response = requests.post(f"{ESP32_IP}/api/arm/command", json={"command": "EMERGENCY_STOP"}, timeout=2)
                if response.status_code == 200:
                    for j in ["base", "shoulder", "elbow", "wrist"]:
                        JOINTS[j]["current_angle"] = 90
                    JOINTS["gripper"]["current_state"] = "open"
                    return {"status": "success", "message": "Emergency stop executed - all joints reset to 90 degrees, gripper open"}
                else:
                    return {"status": "error", "message": f"ESP32 returned error: {response.text}"}
            except requests.Timeout:
                return {"status": "error", "message": "ESP32 connection timeout - check if device is powered on and connected to WiFi"}
            except requests.ConnectionError:
                return {"status": "error", "message": "Cannot connect to ESP32 - check IP address and network connection"}
            except Exception as e:
                return {"status": "error", "message": f"Communication error: {str(e)}"}
        
        elif joint == "gripper":
            # Get current state (convert to lowercase for comparison)
            current_state = JOINTS["gripper"]["current_state"].lower()
            target_state = value.lower() if value else None
            
            if target_state not in ["open", "closed"]:
                return {"status": "error", "message": "Invalid gripper state (must be 'open' or 'closed')"}
            
            # Check if we need to toggle
            if current_state != target_state:
                try:
                    response = requests.post(f"{ESP32_IP}/api/arm/command", json={"command": "GRIPPER_TOGGLE"}, timeout=2)
                    if response.status_code == 200:
                        JOINTS["gripper"]["current_state"] = target_state
                        return {"status": "success", "message": f"Gripper is now {target_state}"}
                    else:
                        return {"status": "error", "message": f"ESP32 returned error: {response.text}"}
                except requests.Timeout:
                    return {"status": "error", "message": "ESP32 connection timeout - check if device is powered on and connected to WiFi"}
                except requests.ConnectionError:
                    return {"status": "error", "message": "Cannot connect to ESP32 - check IP address and network connection"}
                except Exception as e:
                    return {"status": "error", "message": f"Communication error: {str(e)}"}
            else:
                return {"status": "success", "message": f"Gripper is already {target_state}"}
        
        else:
            if joint not in JOINTS:
                return {"status": "error", "message": "Invalid joint"}
            
            try:
                angle = int(value)
                min_angle = JOINTS[joint]["min_angle"]
                max_angle = JOINTS[joint]["max_angle"]
                
                if not (min_angle <= angle <= max_angle):
                    return {"status": "error", "message": f"Angle out of range ({min_angle} to {max_angle})"}
                
                # Map joint names to Arduino command names
                command_mapping = {
                    "base": "WAIST",
                    "shoulder": "SHOULDER",
                    "elbow": "ELBOW",
                    "wrist": "WRIST"
                }
                command_prefix = command_mapping[joint]
                
                current_angle = JOINTS[joint]["current_angle"]
                # Calculate how many 5-degree steps needed
                total_steps = abs(angle - current_angle) // 5
                if total_steps == 0:
                    return {"status": "success", "message": f"{joint.title()} already at {angle} degrees"}
                
                # Determine direction based on joint type
                if joint in ["base", "wrist"]:
                    # For base and wrist, use LEFT/RIGHT
                    if angle > current_angle:
                        direction = "RIGHT"
                    else:
                        direction = "LEFT"
                else:
                    # For shoulder and elbow, use UP/DOWN
                    if angle > current_angle:
                        direction = "UP"
                    else:
                        direction = "DOWN"
                
                command = f"{command_prefix}_{direction}"
                
                # Send the command multiple times to reach the target angle
                for i in range(total_steps):
                    try:
                        response = requests.post(f"{ESP32_IP}/api/arm/command", json={"command": command}, timeout=2)
                        if response.status_code != 200:
                            return {"status": "error", "message": f"ESP32 returned error: {response.text}"}
                    except requests.Timeout:
                        return {"status": "error", "message": "ESP32 connection timeout - check if device is powered on and connected to WiFi"}
                    except requests.ConnectionError:
                        return {"status": "error", "message": "Cannot connect to ESP32 - check IP address and network connection"}
                    except Exception as e:
                        return {"status": "error", "message": f"Communication error: {str(e)}"}
                
                # Update current angle
                if direction in ["UP", "RIGHT"]:
                    JOINTS[joint]["current_angle"] = min(JOINTS[joint]["current_angle"] + (total_steps * 5), max_angle)
                else:
                    JOINTS[joint]["current_angle"] = max(JOINTS[joint]["current_angle"] - (total_steps * 5), min_angle)
                
                return {"status": "success", "message": f"Moved {joint} to {angle} degrees"}
            
            except ValueError:
                return {"status": "error", "message": "Invalid angle value"}
    
    except requests.RequestException as e:
        return {"status": "error", "message": f"Failed to communicate with ESP32: {str(e)}"}

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return jsonify({"response": "Please provide a command or type 'help' for examples."}), 400
    
    # Check for help requests
    user_message_lower = user_message.lower()
    if 'help' in user_message_lower or 'what can i do' in user_message_lower or 'how to use' in user_message_lower:
        result = handle_help_request()
    else:
        # Check for greetings
        greeting_result = handle_greeting(user_message)
        if greeting_result:
            result = greeting_result
        else:
            # Parse command using Gemini
            parsed_command = parse_command(user_message)
            
            # Check if the input is a valid robotic arm command
            if parsed_command.get("joint") != "error":
                # Send command to ESP32
                result = send_to_esp32(parsed_command)
            else:
                # Return example commands for invalid or irrelevant inputs
                result = handle_help_request()
    
    # Prepare response
    response_text = result.get("message", "Unknown error")
    if result.get("status") == "success":
        response_text = f"✅ {response_text}"
    else:
        response_text = f"❌ {response_text}"
    
    return jsonify({"response": response_text})

@app.route('/telemetry', methods=['GET'])
def telemetry():
    try:
        response = requests.get(f"{ESP32_IP}/api/arm/telemetry")
        if response.status_code == 200:
            data = response.json()
            for joint in ["base", "shoulder", "elbow", "wrist"]:
                JOINTS[joint]["current_angle"] = data.get(f"{joint}Angle", JOINTS[joint]["current_angle"])
            JOINTS["gripper"]["current_state"] = data.get("gripperState", "Open").lower()
            return jsonify(data)
        else:
            return jsonify({"status": "error", "message": "Failed to fetch telemetry"}), 500
    except requests.RequestException as e:
        return jsonify({"status": "error", "message": f"Failed to communicate with ESP32: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)