-- Create database if it doesn't exist
CREATE DATABASE IF NOT EXISTS drone_db;
USE drone_db;

-- Create drone_controls table
CREATE TABLE IF NOT EXISTS drone_controls (
    id INT AUTO_INCREMENT PRIMARY KEY,
    control_name VARCHAR(50) NOT NULL,
    control_value VARCHAR(255) NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Insert default values if not already present
INSERT INTO drone_controls (control_name, control_value)
SELECT 'movement', 'stop'
WHERE NOT EXISTS (SELECT 1 FROM drone_controls WHERE control_name = 'movement');

INSERT INTO drone_controls (control_name, control_value)
SELECT 'headlights', 'off'
WHERE NOT EXISTS (SELECT 1 FROM drone_controls WHERE control_name = 'headlights');

INSERT INTO drone_controls (control_name, control_value)
SELECT 'lcd_message', 'Hello Drone!'
WHERE NOT EXISTS (SELECT 1 FROM drone_controls WHERE control_name = 'lcd_message');

-- Create a sample database user with appropriate permissions
-- GRANT ALL PRIVILEGES ON drone_db.* TO 'drone_user'@'localhost' IDENTIFIED BY 'your_password';
-- FLUSH PRIVILEGES;