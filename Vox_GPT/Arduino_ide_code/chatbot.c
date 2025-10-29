#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <Servo.h>
#include <ArduinoJson.h>

// WiFi credentials
const char* ssid = "Nisha 4g"; // Replace with your WiFi SSID
const char* password = "khush292009"; // Replace with your WiFi password

// Servo pin definitions (ESP8266 GPIO pins)
#define BASE_PIN D4
#define SHOULDER_PIN D5
#define ELBOW_PIN D6
#define WRIST_PIN D7
#define GRIPPER_PIN D8

// Servo objects
Servo baseServo;
Servo shoulderServo;
Servo elbowServo;
Servo wristServo;
Servo gripperServo;

// Servo angles and state (using logical angles that map to 0-180 servo range)
int baseAngle = 90; // Center position (logical)
int shoulderAngle = 90;
int elbowAngle = 90;
int wristAngle = 90;
bool gripperState = false; // false = Open, true = Closed

// Helper function to convert logical angle (-180 to 180) to servo angle (0 to 180)
int mapToServoAngle(int logicalAngle) {
  return constrain(logicalAngle + 90, 0, 180);
}

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
  baseServo.write(mapToServoAngle(baseAngle));
  shoulderServo.write(shoulderAngle);
  elbowServo.write(elbowAngle);
  wristServo.write(mapToServoAngle(wristAngle));
  gripperServo.write(gripperState ? 0 : 180); // 0 = Closed, 180 = Open

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
      baseAngle = constrain(baseAngle - 5, -180, 180);
      baseServo.write(mapToServoAngle(baseAngle));
      delay(50); // Small delay for servo movement
    } else if (command == "WAIST_RIGHT") {
      baseAngle = constrain(baseAngle + 5, -180, 180);
      baseServo.write(mapToServoAngle(baseAngle));
      delay(50);
    } else if (command == "SHOULDER_UP") {
      shoulderAngle = constrain(shoulderAngle + 5, 0, 170);
      shoulderServo.write(shoulderAngle);
      delay(50);
    } else if (command == "SHOULDER_DOWN") {
      shoulderAngle = constrain(shoulderAngle - 5, 0, 170);
      shoulderServo.write(shoulderAngle);
      delay(50);
    } else if (command == "ELBOW_UP") {
      elbowAngle = constrain(elbowAngle + 5, 0, 170);
      elbowServo.write(elbowAngle);
      delay(50);
    } else if (command == "ELBOW_DOWN") {
      elbowAngle = constrain(elbowAngle - 5, 0, 170);
      elbowServo.write(elbowAngle);
      delay(50);
    } else if (command == "WRIST_LEFT") {
      wristAngle = constrain(wristAngle - 5, -180, 180);
      wristServo.write(mapToServoAngle(wristAngle));
      delay(50);
    } else if (command == "WRIST_RIGHT") {
      wristAngle = constrain(wristAngle + 5, -180, 180);
      wristServo.write(mapToServoAngle(wristAngle));
      delay(50);
    } else if (command == "GRIPPER_TOGGLE") {
      gripperState = !gripperState;
      gripperServo.write(gripperState ? 0 : 180);
      delay(50);
    } else if (command == "EMERGENCY_STOP") {
      baseAngle = 90;
      shoulderAngle = 90;
      elbowAngle = 90;
      wristAngle = 90;
      gripperState = false;
      baseServo.write(mapToServoAngle(baseAngle));
      shoulderServo.write(shoulderAngle);
      elbowServo.write(elbowAngle);
      wristServo.write(mapToServoAngle(wristAngle));
      gripperServo.write(180);
      delay(100);
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
  doc["boardType"] = "ESP8266";

  String response;
  serializeJson(doc, response);
  server.send(200, "application/json", response);
}