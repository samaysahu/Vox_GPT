import cv2
import numpy as np
import serial
import time
import speech_recognition as sr
import threading

# Open the camera (0 for default webcam)
cap = cv2.VideoCapture(0)

# Set up serial communication with Arduino
try:
    ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)  # Change COM port as needed
    time.sleep(2)  # Wait for the serial connection to initialize
except serial.SerialException as e:
    print(f"Error: Could not open serial port: {e}")
    exit()

# Smooth arm movement function
def move_arm_smooth(start_pos, end_pos, steps=10, delay=0.1):
    for i in range(steps + 1):
        intermediate_pos = [
            int(start_pos[j] + (end_pos[j] - start_pos[j]) * (i / steps))
            for j in range(4)
        ]
        command = f"{intermediate_pos[0]} {intermediate_pos[1]} {intermediate_pos[2]} {intermediate_pos[3]}\n"
        try:
            ser.write(command.encode())
        except serial.SerialException as e:
            print(f"Error writing to serial port: {e}")
            print("Please check the connection to the ESP8266 and restart the script.")
            return  # Stop trying to move the arm if writing fails
        time.sleep(delay)


# Define arm positions
pick_position = [135, 40, 90, 45]
white_after_pick_position = [135, 180, 180, 45]
white_position = [105, 135, 150, 90]
blue_after_pick_position = [135, 180, 180, 45]
blue_position = [160, 110, 130, 90]
other_after_pick_position = [135, 90, 140, 45]
other_drop_position = [25, 150, 180, 90]
initial_position = [125, 180, 90, 90]

start_detection = False
detection_complete = True
voice_mode = False
voice_command = None

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

# Voice recognition
def listen_for_voice():
    global voice_command, voice_mode
    recognizer = sr.Recognizer()
    microphone = sr.Microphone()

    with microphone as source:
        print("Listening for voice command...")
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)

    try:
        command = recognizer.recognize_google(audio).lower()
        print("You said:", command)
        if "blue" in command:
            voice_command = "blue"
            return True
        elif "white" in command:
            voice_command = "white"
            return True
        else:
            print("Command not recognized. Please say 'pick the blue box' or 'pick the white box'")
            return False
    except sr.UnknownValueError:
        print("Could not understand audio")
        return False
    except sr.RequestError as e:
        print(f"Could not request results; {e}")
        return False

# Process voice-controlled movement
def process_voice_command():
    global voice_command, start_detection, detection_complete, voice_mode

    if voice_command:
        ret, frame = cap.read()
        if not ret:
            return

        h, w, _ = frame.shape
        square_size = 100
        x1, y1 = (w // 2 - square_size // 2, h // 2 - square_size // 2)
        x2, y2 = (w // 2 + square_size // 2, h // 2 + square_size // 2)
        roi = frame[y1:y2, x1:x2]

        detected_color = detect_color(roi)

        if detected_color == voice_command:
            detection_complete = False

            move_arm_smooth(initial_position, pick_position[:3] + [initial_position[3]])
            time.sleep(1)
            move_arm_smooth(pick_position[:3] + [initial_position[3]], pick_position)
            time.sleep(1)

            if voice_command == "white":
                move_arm_smooth(pick_position, white_after_pick_position)
                time.sleep(1)
                move_arm_smooth(white_after_pick_position, white_position[:3] + [10])
                time.sleep(1)
                move_arm_smooth(white_position[:3] + [10], white_position[:3] + [90])
                time.sleep(1)
                move_arm_smooth(white_position[:3] + [90], initial_position)

            elif voice_command == "blue":
                move_arm_smooth(pick_position, blue_after_pick_position)
                time.sleep(1)
                move_arm_smooth(blue_after_pick_position, blue_position[:3] + [10])
                time.sleep(1)
                move_arm_smooth(blue_position[:3] + [10], blue_position[:3] + [90])
                time.sleep(1)
                move_arm_smooth(blue_position[:3] + [90], initial_position)

            detection_complete = True
            start_detection = False
            voice_mode = False
            voice_command = None

        else:
            print(f"{voice_command} box not detected in the frame")
            voice_mode = False
            voice_command = None

# Main loop
while True:
    ret, frame = cap.read()
    if not ret:
        break

    h, w, _ = frame.shape
    square_size = 100
    x1, y1 = (w // 2 - square_size // 2, h // 2 - square_size // 2)
    x2, y2 = (w // 2 + square_size // 2, h // 2 + square_size // 2)
    roi = frame[y1:y2, x1:x2]

    # Status display
    cv2.putText(frame, "Color Mode (Press 'V' for Voice)", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    if voice_mode:
        cv2.putText(frame, "Voice Mode: Listening...", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    elif voice_command:
        cv2.putText(frame, f"Voice Command: {voice_command}", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    if not start_detection and not voice_mode:
        status_text = "Press ENTER to start detection" if detection_complete else "Detection in progress..."
        cv2.putText(frame, status_text, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

    # Object detection mode
    if start_detection:
        detected_type = detect_color(roi)
        print(f"Detected color: {detected_type}")  # Print the detected color

        if detected_type:
            detection_complete = False

            move_arm_smooth(initial_position, pick_position[:3] + [initial_position[3]])
            time.sleep(1)
            move_arm_smooth(pick_position[:3] + [initial_position[3]], pick_position)
            time.sleep(1)

            if detected_type == "white":
                move_arm_smooth(pick_position, white_after_pick_position)
                time.sleep(1)
                move_arm_smooth(white_after_pick_position, white_position[:3] + [10])
                time.sleep(1)
                move_arm_smooth(white_position[:3] + [10], white_position[:3] + [90])
                time.sleep(1)
                move_arm_smooth(white_position[:3] + [90], initial_position)

            elif detected_type == "blue":
                move_arm_smooth(pick_position, blue_after_pick_position)
                time.sleep(1)
                move_arm_smooth(blue_after_pick_position, blue_position[:3] + [10])
                time.sleep(1)
                move_arm_smooth(blue_position[:3] + [10], blue_position[:3] + [90])
                time.sleep(1)
                move_arm_smooth(blue_position[:3] + [90], initial_position)

            else:
                move_arm_smooth(pick_position, other_after_pick_position)
                time.sleep(1)
                move_arm_smooth(other_after_pick_position, other_drop_position[:3] + [10])
                time.sleep(1)
                move_arm_smooth(other_drop_position[:3] + [10], other_drop_position[:3] + [90])
                time.sleep(1)
                move_arm_smooth(other_drop_position[:3] + [90], initial_position)

            detection_complete = True
            start_detection = False

    # Show window
    cv2.imshow("Frame", frame)
    key = cv2.waitKey(1) & 0xFF

    if key == 13 and detection_complete and not voice_mode:  # Enter key = start detection
        start_detection = True
    elif key == ord('v') or key == ord('V'):  # Voice mode
        if detection_complete and not voice_mode:
            voice_mode = True
            voice_thread = threading.Thread(target=listen_for_voice)
            voice_thread.daemon = True
            voice_thread.start()
    elif key == ord('q'):  # Quit
        break

    if voice_command and not start_detection and detection_complete:
        process_voice_command()

cap.release()
ser.close()
cv2.destroyAllWindows()