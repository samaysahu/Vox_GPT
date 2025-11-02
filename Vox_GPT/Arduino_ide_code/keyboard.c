#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <Servo.h>
#include <ArduinoJson.h>

// WiFi credentials
const char* ssid = "Nisha 4g"; // Replace with your WiFi SSID
const char* password = "khush292009"; // Replace with your WiFi password

// Servo pin definitions
#define BASE_PIN D4
#define SHOULDER_PIN D1
#define ELBOW_PIN D5
#define WRIST_PIN D8
#define GRIPPER_PIN D0

// Servo objects
Servo baseServo;
Servo shoulderServo;
Servo elbowServo;
Servo wristServo;
Servo gripperServo;

// Servo angles and state
int baseAngle = 90; // Center position
int shoulderAngle = 90;
int elbowAngle = 90;
int wristAngle = 90;
bool gripperState = false; // false = Open, true = Closed

// Web server on port 80
ESP8266WebServer server(80);

// Setup function
void setup() {
  Serial.begin(115200);

  // Attach servos to pins
  baseServo.attach(BASE_PIN);
  shoulderServo.attach(SHOULDER_PIN);
  elbowServo.attach(ELBOW_PIN);
  wristServo.attach(WRIST_PIN);
  gripperServo.attach(GRIPPER_PIN);

  // Set initial positions
  baseServo.write(baseAngle);
  shoulderServo.write(shoulderAngle);
  elbowServo.write(elbowAngle);
  wristServo.write(wristAngle);
  gripperServo.write(gripperState ? 0 : 180); // 0 = Closed, 180 = Open

  // Connect to WiFi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  Serial.println(WiFi.localIP());

  // Define server endpoints
  server.on("/api/arm/command", HTTP_POST, handleCommand);
  server.on("/api/arm/telemetry", HTTP_GET, handleTelemetry);
  server.begin();
}

// Main loop
void loop() {
  server.handleClient();
}

// Handle command requests
void handleCommand() {
  if (server.hasArg("plain")) {
    StaticJsonDocument<200> doc;
    DeserializationError error = deserializeJson(doc, server.arg("plain"));
    if (error) {
      server.send(400, "application/json", "{\"status\":\"Invalid JSON\"}");
      return;
    }

    String command = doc["command"].as<String>();
    String response = "{\"status\":\"Executing\"}";

    // Process commands
    if (command == "WAIST_LEFT") {
      baseAngle = max(-180, baseAngle - 5);
      baseServo.write(baseAngle);
    } else if (command == "WAIST_RIGHT") {
      baseAngle = min(180, baseAngle + 5);
      baseServo.write(baseAngle);
    } else if (command == "SHOULDER_UP") {
      shoulderAngle = min(170, shoulderAngle + 5);
      shoulderServo.write(shoulderAngle);
    } else if (command == "SHOULDER_DOWN") {
      shoulderAngle = max(0, shoulderAngle - 5);
      shoulderServo.write(shoulderAngle);
    } else if (command == "ELBOW_UP") {
      elbowAngle = min(170, elbowAngle + 5);
      elbowServo.write(elbowAngle);
    } else if (command == "ELBOW_DOWN") {
      elbowAngle = max(0, elbowAngle - 5);
      elbowServo.write(elbowAngle);
    } else if (command == "WRIST_LEFT") {
      wristAngle = max(-180, wristAngle - 5);
      wristServo.write(wristAngle);
    } else if (command == "WRIST_RIGHT") {
      wristAngle = min(180, wristAngle + 5);
      wristServo.write(wristAngle);
    } else if (command == "GRIPPER_TOGGLE") {
      gripperState = !gripperState;
      gripperServo.write(gripperState ? 0 : 180);
    } else if (command == "EMERGENCY_STOP") {
      baseAngle = 90;
      shoulderAngle = 90;
      elbowAngle = 90;
      wristAngle = 90;
      gripperState = false;
      baseServo.write(baseAngle);
      shoulderServo.write(shoulderAngle);
      elbowServo.write(elbowAngle);
      wristServo.write(wristAngle);
      gripperServo.write(180);
      response = "{\"status\":\"Stopped\"}";
    } else {
      server.send(400, "application/json", "{\"status\":\"Invalid command\"}");
      return;
    }

    server.send(200, "application/json", response);
  } else {
    server.send(400, "application/json", "{\"status\":\"No command provided\"}");
  }
}

// Handle telemetry requests
void handleTelemetry() {
  StaticJsonDocument<200> doc;
  doc["baseAngle"] = baseAngle;
  doc["shoulderAngle"] = shoulderAngle;
  doc["elbowAngle"] = elbowAngle;
  doc["wristAngle"] = wristAngle;
  doc["gripperState"] = gripperState ? "Closed" : "Open";
  doc["systemStatus"] = (WiFi.status() == WL_CONNECTED) ? "Operational" : "Error";

  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}