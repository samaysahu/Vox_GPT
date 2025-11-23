#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <Servo.h>
#include <ArduinoJson.h>

// WiFi credentials
const char* ssid = "Samay"; // Replace with your WiFi SSID
const char* password = "robotechzone"; // Replace with your WiFi password

// Servo pin definitions
#define BASE_PIN D4
#define SHOULDER_PIN D1
#define ELBOW_PIN D5
#define WRIST_PIN D6
#define GRIPPER_PIN D7

// Servo objects
Servo baseServo;
Servo shoulderServo;
Servo elbowServo;
Servo wristServo;
Servo gripperServo;

// --- Non-Blocking Movement State ---
// Current angles are read directly from servos
// Target angles for the non-blocking movement
int targetBaseAngle = 90;
int targetShoulderAngle = 90;
int targetElbowAngle = 90;
int targetWristAngle = 90;
int targetGripperAngle = 120; // 0 for closed, 120 for open

// State for the gripper
bool gripperState = false; // false = Open, true = Closed

// Timing for non-blocking updates
unsigned long lastMoveTime = 0;
const int MOVE_DELAY = 20; // ms between each 1-degree step

ESP8266WebServer server(80);

// Setup function
void setup() {
  Serial.begin(115200);

  baseServo.attach(BASE_PIN);
  shoulderServo.attach(SHOULDER_PIN);
  elbowServo.attach(ELBOW_PIN);
  wristServo.attach(WRIST_PIN);
  gripperServo.attach(GRIPPER_PIN);

  // Set initial positions
  baseServo.write(targetBaseAngle);
  shoulderServo.write(targetShoulderAngle);
  elbowServo.write(targetElbowAngle);
  wristServo.write(targetWristAngle);
  gripperServo.write(targetGripperAngle); // Initialize gripper with target

  // Connect to WiFi
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected!");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());

  server.on("/api/arm/command", HTTP_POST, handleCommand);
  server.on("/api/arm/telemetry", HTTP_GET, handleTelemetry);
  server.begin();
}

// Main loop - handles web requests and non-blocking movement
void loop() {
  server.handleClient();

  // Non-blocking servo movement logic
  if (millis() - lastMoveTime > MOVE_DELAY) {
    lastMoveTime = millis();

    // Move servos one by one, only proceeding to the next if the current one is at its target
    // Desired order: Elbow, Base, Shoulder, Wrist, Gripper

    int currentElbow = elbowServo.read();
    if (currentElbow != targetElbowAngle) {
      int step = (targetElbowAngle > currentElbow) ? 1 : -1;
      elbowServo.write(currentElbow + step);
      return; // Process one servo move per loop iteration
    }

    int currentBase = baseServo.read();
    if (currentBase != targetBaseAngle) {
      int step = (targetBaseAngle > currentBase) ? 1 : -1;
      baseServo.write(currentBase + step);
      return;
    }

    int currentShoulder = shoulderServo.read();
    if (currentShoulder != targetShoulderAngle) {
      int step = (targetShoulderAngle > currentShoulder) ? 1 : -1;
      shoulderServo.write(currentShoulder + step);
      return;
    }
    
    int currentWrist = wristServo.read();
    if (currentWrist != targetWristAngle) {
      int step = (targetWristAngle > currentWrist) ? 1 : -1;
      wristServo.write(currentWrist + step);
      return;
    }

    int currentGripper = gripperServo.read();
    if (currentGripper != targetGripperAngle) {
      int step = (targetGripperAngle > currentGripper) ? 1 : -1;
      gripperServo.write(currentGripper + step);
      return;
    }
  }
}

// Handle command requests
void handleCommand() {
  if (!server.hasArg("plain")) {
    server.send(400, "application/json", "{\"status\":\"No command provided\"}");
    return;
  }

  StaticJsonDocument<256> doc;
  DeserializationError error = deserializeJson(doc, server.arg("plain"));
  if (error) {
    server.send(400, "application/json", "{\"status\":\"Invalid JSON\"}");
    return;
  }

  String command = doc["command"].as<String>();

  if (command == "SET_ANGLES") {
    // Update the target angles. The main loop() will handle the movement.
    if (doc.containsKey("base")) {
      targetBaseAngle = constrain(doc["base"].as<int>(), 0, 180);
    }
    if (doc.containsKey("shoulder")) {
      targetShoulderAngle = constrain(doc["shoulder"].as<int>(), 0, 170);
    }
    if (doc.containsKey("elbow")) {
      targetElbowAngle = constrain(doc["elbow"].as<int>(), 0, 170);
    }
    if (doc.containsKey("wrist")) {
      targetWristAngle = constrain(doc["wrist"].as<int>(), 0, 180);
    }
    
    // Handle optional gripper command
    if (doc.containsKey("gripper")) {
      String gripperCmd = doc["gripper"];
      if (gripperCmd == "close") {
        targetGripperAngle = 0;
        gripperState = true;
      } else if (gripperCmd == "open") {
        targetGripperAngle = 120;
        gripperState = false;
      }
    }
    server.send(200, "application/json", "{\"status\":\"Movement initiated\"}");
  } else if (command == "GRIPPER_TOGGLE") {
    // This command is now primarily for toggling, but can also be used for explicit open/close
    if (doc.containsKey("gripper")) {
      String gripperCmd = doc["gripper"];
      if (gripperCmd == "close") {
        targetGripperAngle = 0;
        gripperState = true;
      } else if (gripperCmd == "open") {
        targetGripperAngle = 120;
        gripperState = false;
      }
    } else { // Toggle if no explicit state is given
      gripperState = !gripperState;
      targetGripperAngle = gripperState ? 120 : 0;
    }
    server.send(200, "application/json", "{\"status\":\"Gripper movement initiated\"}");
  } else if (command == "EMERGENCY_STOP") {
    // Set targets to home position
    targetBaseAngle = 90;
    targetShoulderAngle = 90;
    targetElbowAngle = 90;
    targetWristAngle = 90;
    targetGripperAngle = 120; // Open gripper
    gripperState = false;
    server.send(200, "application/json", "{\"status\":\"Stop initiated\"}");
  } else {
    // Legacy incremental commands are no longer supported by this firmware
    // as they are inefficient. The backend should handle specific angle commands.
    server.send(400, "application/json", "{\"status\":\"Legacy commands not supported\"}");
  }
}

// Handle telemetry requests
void handleTelemetry() {
  StaticJsonDocument<200> doc;
  doc["baseAngle"] = baseServo.read();
  doc["shoulderAngle"] = shoulderServo.read();
  doc["elbowAngle"] = elbowServo.read();
  doc["wristAngle"] = wristServo.read();
  doc["gripperState"] = gripperState ? "Closed" : "Open";
  doc["systemStatus"] = (WiFi.status() == WL_CONNECTED) ? "Operational" : "Error";
  doc["boardType"] = "ESP8266";

  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}
