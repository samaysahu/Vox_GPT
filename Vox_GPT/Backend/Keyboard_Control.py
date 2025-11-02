from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import time

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# ESP8266 IP address (replace with the IP from Serial Monitor)
ESP8266_IP = "192.168.29.247"  # Update with your ESP8266's IP
ARM_API_ENDPOINT = f"http://{ESP8266_IP}/api/arm/command"
TELEMETRY_ENDPOINT = f"http://{ESP8266_IP}/api/arm/telemetry"

# Serve the frontend HTML
@app.route('/')
def serve_frontend():
    return send_file('../Frontend/Keyboard_Control.html')

# Handle arm commands
@app.route('/api/arm/command', methods=['POST'])
def arm_command():
    try:
        data = request.get_json()
        if not data or 'command' not in data:
            return jsonify({"status": "No command provided"}), 400
        
        # Forward command to ESP8266
        response = requests.post(ARM_API_ENDPOINT, json=data, timeout=5)
        if response.status_code == 200:
            return jsonify(response.json()), 200
        else:
            return jsonify({"status": "ESP8266 error"}), response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"status": f"Failed to reach ESP8266: {str(e)}"}), 500

# Handle telemetry requests
@app.route('/api/arm/telemetry', methods=['GET'])
def arm_telemetry():
    try:
        response = requests.get(TELEMETRY_ENDPOINT, timeout=5)
        if response.status_code == 200:
            return jsonify(response.json()), 200
        else:
            return jsonify({"status": "ESP8266 error"}), response.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"status": f"Failed to reach ESP8266: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)