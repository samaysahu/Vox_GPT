# Vox_GPT

Vox_GPT is a project that allows you to control a robotic arm using natural language commands through a web-based chat interface. The project uses a Python backend with the Gemini API to understand commands, and an ESP8266 microcontroller to control the arm's servos.

## Features

-   **Natural Language Control:** Control a robotic arm using plain English commands.
-   **Web-Based Interface:** An intuitive and visually appealing chat interface to interact with the robotic arm.
-   **AI-Powered:** Uses Google's Gemini API to parse and understand user commands.
-   **Real-time Control:** Commands are sent to the robotic arm in real-time over WiFi.

## System Architecture

The project consists of three main components:

1.  **Frontend:** A static HTML file with JavaScript that provides the user interface for the chatbot. It sends user messages to the backend and displays the responses.
2.  **Backend:** A Python Flask server that receives messages from the frontend. It uses the Gemini API to parse the natural language commands into structured data that the robotic arm can understand. It then sends these commands to the ESP8266.
3.  **Robotic Arm (ESP8266):** An ESP8266 microcontroller runs code to control the servos of the robotic arm. It connects to your local WiFi and exposes an API to receive commands from the backend.

```
[User] -> [Frontend (chatbot.html)] -> [Backend (chatbot.py)] -> [ESP8266 (robotic arm)]
```

## Hardware Requirements

-   An ESP8266-based microcontroller board (e.g., NodeMCU, Wemos D1 Mini).
-   A robotic arm with 5 servo motors (base, shoulder, elbow, wrist, gripper).
-   Jumper wires to connect the servos to the ESP8266.
-   A separate power supply for the servos.

## Software Requirements

-   [Arduino IDE](https://www.arduino.cc/en/software) with support for the ESP8266 board.
-   [Python 3.7+](https://www.python.org/downloads/)
-   A modern web browser (e.g., Chrome, Firefox).
-   [Git](https://git-scm.com/downloads) for cloning the repository.

## Setup Instructions

### 1. Clone the Repository

```bash
git clone git@github.com:samaysahu/Vox_GPT.git
cd Vox_GPT
```

### 2. Backend Setup

1.  **Navigate to the Backend Directory:**
    ```bash
    cd Vox_GPT/Backend
    ```

2.  **Create and Activate a Virtual Environment:**
    -   On macOS and Linux:
        ```bash
        python3 -m venv venv
        source venv/bin/activate
        ```
    -   On Windows:
        ```bash
        python -m venv venv
        .\venv\Scripts\activate
        ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    -   The `.env` file holds your Gemini API key. Rename the example file and add your key:
        ```bash
        mv .env.example .env
        ```
    -   Open the `.env` file and replace `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` with your actual Gemini API key.
        ```
        GEMINI_API_KEY=your_gemini_api_key
        ```

### 3. Arduino/ESP8266 Setup

1.  **Configure Arduino IDE for ESP8266:**
    -   Open the Arduino IDE.
    -   Go to `File > Preferences`.
    -   In the "Additional Boards Manager URLs" field, add the following URL:
        ```
        http://arduino.esp8266.com/stable/package_esp8266com_index.json
        ```
    -   Go to `Tools > Board > Boards Manager...`.
    -   Search for "esp8266" and install the `esp8266` by `ESP8266 Community`.

2.  **Install Required Library:**
    -   Go to `Tools > Manage Libraries...`.
    -   Search for and install `ArduinoJson`.

3.  **Prepare the Arduino Code:**
    -   The provided Arduino code is in `Arduino_ide_code/chatbot.c`. It is recommended to rename this file to `chatbot.ino` to open it correctly in the Arduino IDE.
    -   Open `chatbot.ino` in the Arduino IDE.

4.  **Update WiFi Credentials:**
    -   Inside the `chatbot.ino` file, find the following lines and replace them with your WiFi network's SSID and password:
        ```cpp
        const char* ssid = "Your_WiFi_SSID";
        const char* password = "Your_WiFi_Password";
        ```

5.  **Upload the Code:**
    -   Connect your ESP8266 board to your computer.
    -   In the Arduino IDE, go to `Tools > Board` and select your ESP8266 board model (e.g., "NodeMCU 1.0 (ESP-12E Module)").
    -   Select the correct COM port under `Tools > Port`.
    -   Click the "Upload" button.

6.  **Find the ESP8266 IP Address:**
    -   After the upload is complete, open the Serial Monitor (`Tools > Serial Monitor`) and set the baud rate to `115200`.
    -   The ESP8266 will print its IP address once it connects to your WiFi network. Note this IP address down.

### 4. Update Backend with ESP8266 IP

-   Open the `Vox_GPT/Backend/chatbot.py` file.
-   Find the `ESP32_IP` variable and replace the placeholder IP address with the one you noted from the Arduino Serial Monitor.
    ```python
    # Note: The variable is named ESP32_IP but the code is for an ESP8266
    ESP32_IP = "http://your_esp8266_ip_address"
    ```

## Running the Application

1.  **Start the Backend Server:**
    -   Make sure you are in the `Vox_GPT/Backend` directory and your virtual environment is activated.
    -   Run the Flask application:
        ```bash
        python chatbot.py
        ```
    -   The server will start on `http://localhost:5000`.

2.  **Open the Frontend:**
    -   Navigate to the `Vox_GPT/Frontend` directory.
    -   Open the `chatbot.html` file in your web browser.

## How to Use

-   Simply type your commands into the chat box and press Enter or click the send button.
-   The chatbot will interpret your command and send it to the robotic arm.

### Example Commands

-   `move the base to 90 degrees`
-   `open the gripper`
-   `close the gripper`
-   `move the shoulder up`
-   `set the elbow to 45 degrees`
-   `emergency stop`

## Project Structure

```
Vox_GPT/
├── Arduino_ide_code/
│   └── chatbot.c       # Code for the ESP8266 microcontroller.
├── Backend/
│   ├── chatbot.py      # Flask backend server.
│   ├── requirements.txt# Python dependencies.
│   └── .env            # Environment variables (Gemini API key).
└── Frontend/
    └── chatbot.html    # The main web interface for the chatbot.
```

## Troubleshooting

-   **Cannot connect to ESP32/ESP8266:**
    -   Ensure the ESP8266 is powered on and connected to the same WiFi network as the computer running the backend.
    -   Double-check that the IP address in `chatbot.py` is correct.
    -   Try to ping the ESP8266's IP address from your computer to verify the connection.
-   **Python dependencies not installing:**
    -   Make sure you have activated the virtual environment before running `pip install`.
-   **"Voice input is not implemented yet" message:**
    -   The microphone button in the UI is a placeholder for future development and is not currently functional.
