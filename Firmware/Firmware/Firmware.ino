// Include Libraries
#include "Arduino.h"
#include "NewPing.h"
#include "LiquidCrystal_PCF8574.h"
#include "LDR.h"
#include "LED.h"
#include "PiezoSpeaker.h"
#include "SoftwareSerial.h"

// Pin Definitions
#define HCSR04_PIN_TRIG	3
#define HCSR04_PIN_ECHO	2
#define LDR_PIN_SIG	A3
#define LEDR_1_PIN_VIN	5
#define LEDR_2_PIN_VIN	6
#define THINSPEAKER_PIN_POS	4
// Motor driver pins
#define MOTOR_DRIVE_PIN1 8
#define MOTOR_DRIVE_PIN2 9
#define MOTOR_STEER_PIN1 10
#define MOTOR_STEER_PIN2 11
// Serial communication pins
#define RX_PIN 12
#define TX_PIN 13

// Global variables and defines
#define LCD_ADDRESS 0x27
#define LCD_ROWS 2
#define LCD_COLUMNS 16
#define SCROLL_DELAY 150
#define BACKLIGHT 255
#define THRESHOLD_ldr 100
#define OBSTACLE_DISTANCE 15  // Distance in cm to stop when reversing
#define AUTO_HEADLIGHT_THRESHOLD 40  // Light level threshold for auto headlights

// Serial communication variables
SoftwareSerial piSerial(RX_PIN, TX_PIN);  // RX, TX
String inputBuffer = "";
boolean stringComplete = false;
unsigned long lastSerialCheck = 0;
const unsigned long serialCheckInterval = 50;  // Check serial more frequently

// Motor control variables
String driveMotorState = "stop";  // forward, backward, stop
String steeringState = "center";  // left, center, right
String headlightsState = "off";   // on, off
String lcdMessage = "Hello Drone!";
unsigned long lastCommandCheck = 0;
const unsigned long commandCheckInterval = 2000;  // Send sensor data every 2 seconds
unsigned long lastSafetyCheck = 0;
const unsigned long safetyCheckInterval = 200;  // Check safety every 200ms
int obstacleDistance = 0;
int lightLevel = 0;
boolean autoHeadlights = true;

// Speaker variables
unsigned int thinSpeakerHoorayLength = 6;
unsigned int thinSpeakerHoorayMelody[] = {NOTE_C4, NOTE_E4, NOTE_G4, NOTE_C5, NOTE_G4, NOTE_C5};
unsigned int thinSpeakerHoorayNoteDurations[] = {8, 8, 8, 4, 8, 4};
boolean alarmActive = false;
unsigned long lastAlarmTime = 0;

// Status tracking
boolean statusChanged = false;
unsigned long lastStatusReport = 0;
const unsigned long statusReportInterval = 1000;  // Report status changes at most once per second

// Object initialization
NewPing hcsr04(HCSR04_PIN_TRIG, HCSR04_PIN_ECHO);
LiquidCrystal_PCF8574 lcdI2C;
LDR ldr(LDR_PIN_SIG);
LED ledR_1(LEDR_1_PIN_VIN);
LED ledR_2(LEDR_2_PIN_VIN);
PiezoSpeaker thinSpeaker(THINSPEAKER_PIN_POS);

void setup() {
  // Initialize hardware serial communication with the computer for debugging
  Serial.begin(9600);
  Serial.println("Starting Remote Control Drone");
  
  // Initialize software serial communication with the serial bridge
  piSerial.begin(9600);
  
  // Initialize the lcd
  lcdI2C.begin(LCD_COLUMNS, LCD_ROWS, LCD_ADDRESS, BACKLIGHT);
  lcdI2C.clear();
  lcdI2C.print("Initializing...");
  
  // Initialize motor pins
  pinMode(MOTOR_DRIVE_PIN1, OUTPUT);
  pinMode(MOTOR_DRIVE_PIN2, OUTPUT);
  pinMode(MOTOR_STEER_PIN1, OUTPUT);
  pinMode(MOTOR_STEER_PIN2, OUTPUT);
  
  // Stop motors initially
  stopDriveMotor();
  centerSteering();
  
  // Send a startup message via serial
  piSerial.println("STATUS:BOOT=complete");
  
  // Request initial control values from the serial bridge
  requestControlValues();
  
  lcdI2C.clear();
  lcdI2C.print("Ready!");
  delay(1000);
  updateLCD(lcdMessage);
}

void loop() {
  // Check for incoming serial commands more frequently
  if (millis() - lastSerialCheck >= serialCheckInterval) {
    receiveCommands();
    lastSerialCheck = millis();
  }
  
  // Read sensor data and send data periodically
  if (millis() - lastCommandCheck >= commandCheckInterval) {
    readSensors();
    sendSensorData();
    lastCommandCheck = millis();
  }
  
  // Check safety more frequently but not every loop
  if (millis() - lastSafetyCheck >= safetyCheckInterval) {
    // Quick distance check for safety
    int quickDistance = hcsr04.ping_cm();
    if (quickDistance > 0) {
      obstacleDistance = quickDistance; // Update only if we got a valid reading
    }
    safetyCheck();
    lastSafetyCheck = millis();
  }
  
  // Apply the controls based on current states
  applyControls();
  
  // Auto headlights feature
  checkAutoHeadlights();
  
  // Report status changes if needed
  reportStatusChanges();
}

// Read all sensor values
void readSensors() {
  // Read distance from ultrasonic sensor
  int tempDistance = hcsr04.ping_cm();
  if (tempDistance > 0) {
    obstacleDistance = tempDistance;
  } else if (obstacleDistance == 0) {
    obstacleDistance = 999; // No obstacle detected
  }
  
  // Read light level from LDR
  lightLevel = ldr.read();
}

// Process serial commands from the bridge
void receiveCommands() {
  while (piSerial.available()) {
    char inChar = (char)piSerial.read();
    
    // If end of command, process it
    if (inChar == '\n') {
      processCommand(inputBuffer);
      inputBuffer = "";
    } else {
      inputBuffer += inChar;
    }
  }
  
  // Also check hardware serial for debugging
  while (Serial.available()) {
    char inChar = (char)Serial.read();
    
    // If end of command, process it
    if (inChar == '\n') {
      processCommand(inputBuffer);
      Serial.println("Processed command: " + inputBuffer);
      inputBuffer = "";
    } else {
      inputBuffer += inChar;
    }
  }
}

// Process the command received
void processCommand(String command) {
  command.trim(); // Remove any leading/trailing whitespace
  Serial.println("Command received: " + command);
  
  if (command.startsWith("GET_ALL")) {
    // Request all control values
    requestControlValues();
  } 
  else if (command.startsWith("DRIVE:")) {
    // Update drive motor state
    String newState = command.substring(6);
    newState.trim();
    
    // Only update if different to avoid loops
    if (newState != driveMotorState) {
      driveMotorState = newState;
      statusChanged = true;
      Serial.println("Drive motor set to: " + driveMotorState);
    }
  } 
  else if (command.startsWith("STEER:")) {
    // Update steering state
    String newState = command.substring(6);
    newState.trim();
    
    // Only update if different
    if (newState != steeringState) {
      steeringState = newState;
      statusChanged = true;
      Serial.println("Steering set to: " + steeringState);
    }
  } 
  else if (command.startsWith("LIGHTS:")) {
    // Update headlights state
    String newState = command.substring(7);
    newState.trim();
    
    // Only update if different
    if (newState != headlightsState) {
      headlightsState = newState;
      statusChanged = true;
      Serial.println("Headlights set to: " + headlightsState);
    }
  } 
  else if (command.startsWith("LCD:")) {
    // Update LCD message
    String newMessage = command.substring(4);
    
    // Only update if different
    if (newMessage != lcdMessage) {
      lcdMessage = newMessage;
      updateLCD(lcdMessage);
      Serial.println("LCD message updated: " + lcdMessage);
    }
  }
  else if (command.startsWith("AUTO_LIGHTS:")) {
    // Enable/disable auto headlights
    String autoState = command.substring(11);
    autoState.trim();
    boolean newAutoState = (autoState == "on");
    
    // Only update if different
    if (newAutoState != autoHeadlights) {
      autoHeadlights = newAutoState;
      statusChanged = true;
      Serial.println("Auto headlights: " + autoState);
    }
  }
  else if (command.startsWith("PING")) {
    // Respond to ping request
    piSerial.println("PONG");
    Serial.println("Ping received, responded with PONG");
  }
}

// Send sensor data to the bridge
void sendSensorData() {
  String sensorData = "SENSORS:";
  sensorData += "DIST=" + String(obstacleDistance) + ";";
  sensorData += "LIGHT=" + String(lightLevel);
  
  piSerial.println(sensorData);
  Serial.println("Sending: " + sensorData);
}

// Report status changes to the bridge
void reportStatusChanges() {
  // Only report if status changed and not too recent
  if (statusChanged && (millis() - lastStatusReport > statusReportInterval)) {
    String statusUpdate = "STATUS:";
    statusUpdate += "DRIVE=" + driveMotorState + ";";
    statusUpdate += "STEER=" + steeringState + ";";
    statusUpdate += "LIGHTS=" + headlightsState;
    
    piSerial.println(statusUpdate);
    Serial.println("Reporting status: " + statusUpdate);
    
    statusChanged = false;
    lastStatusReport = millis();
  }
}

// Request control values from the bridge
void requestControlValues() {
  piSerial.println("REQUEST:CONTROLS");
  Serial.println("Requesting control values from serial bridge");
}

// Apply the current control states to the hardware
void applyControls() {
  // Apply drive motor state
  if (driveMotorState == "forward") {
    driveForward();
  } else if (driveMotorState == "backward") {
    driveBackward();
  } else {
    stopDriveMotor();
  }
  
  // Apply steering state
  if (steeringState == "left") {
    steerLeft();
  } else if (steeringState == "right") {
    steerRight();
  } else {
    centerSteering();
  }
  
  // Apply headlights state if not in auto mode
  if (!autoHeadlights) {
    if (headlightsState == "on") {
      turnOnHeadlights();
    } else {
      turnOffHeadlights();
    }
  }
}

// Safety check for obstacles when moving backward
void safetyCheck() {
  if (driveMotorState == "backward" && obstacleDistance <= OBSTACLE_DISTANCE && obstacleDistance > 0) {
    // If too close to an obstacle while backing up, stop the motor
    stopDriveMotor();
    
    // Only update state if it was actually changed
    if (driveMotorState != "stop") {
      driveMotorState = "stop";
      statusChanged = true;
      
      // Send urgent status update immediately
      piSerial.println("STATUS:DRIVE=stop;REASON=obstacle;DISTANCE=" + String(obstacleDistance));
      Serial.println("Safety stop triggered! Obstacle detected at " + String(obstacleDistance) + "cm");
      
      // Sound alarm if not already sounding
      if (!alarmActive || (millis() - lastAlarmTime > 2000)) {
        thinSpeaker.playMelody(thinSpeakerHoorayLength, thinSpeakerHoorayMelody, thinSpeakerHoorayNoteDurations);
        alarmActive = true;
        lastAlarmTime = millis();
      }
      
      // Display warning on LCD
      lcdI2C.clear();
      lcdI2C.print("WARNING!");
      lcdI2C.selectLine(2);
      lcdI2C.print("Obstacle: " + String(obstacleDistance) + "cm");
      delay(1000);
      updateLCD(lcdMessage); // Return to normal message
    }
  } else {
    alarmActive = false;
  }
}

// Check if auto headlights should be enabled based on light level
void checkAutoHeadlights() {
  if (autoHeadlights) {
    if (lightLevel > AUTO_HEADLIGHT_THRESHOLD) {
      turnOffHeadlights();
    } else {
      turnOnHeadlights();
    }
  }
}

// Update the LCD display
void updateLCD(String message) {
  lcdI2C.clear();
  lcdI2C.print(message);
  
  // If message is too long, scroll it
  if (message.length() > LCD_COLUMNS) {
    delay(1000); // Show beginning of message before scrolling
    for (int pos = 0; pos <= message.length() - LCD_COLUMNS; pos++) {
      lcdI2C.clear();
      lcdI2C.print(message.substring(pos, pos + LCD_COLUMNS));
      delay(SCROLL_DELAY);
    }
  }
}

// Motor control functions
void driveForward() {
  digitalWrite(MOTOR_DRIVE_PIN1, HIGH);
  digitalWrite(MOTOR_DRIVE_PIN2, LOW);
}

void driveBackward() {
  digitalWrite(MOTOR_DRIVE_PIN1, LOW);
  digitalWrite(MOTOR_DRIVE_PIN2, HIGH);
}

void stopDriveMotor() {
  digitalWrite(MOTOR_DRIVE_PIN1, LOW);
  digitalWrite(MOTOR_DRIVE_PIN2, LOW);
}

void steerLeft() {
  analogWrite(MOTOR_STEER_PIN1, 255);
  analogWrite(MOTOR_STEER_PIN2, 0);
}

void steerRight() {
  analogWrite(MOTOR_STEER_PIN1, 0);
  analogWrite(MOTOR_STEER_PIN2, 255);
}

void centerSteering() {
  digitalWrite(MOTOR_STEER_PIN1, LOW);
  digitalWrite(MOTOR_STEER_PIN2, LOW);
}

void turnOnHeadlights() {
  ledR_1.on();
  ledR_2.on();
}

void turnOffHeadlights() {
  ledR_1.off();
  ledR_2.off();
}