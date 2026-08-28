# Kindle Monitor

A lightweight PC performance monitoring dashboard optimized for Kindle's e-ink browser.

## Features
- E-Ink optimized monochrome UI (High contrast, large fonts).
- 3-second auto-refresh without full page reload.
- Tracks CPU, RAM, and GPU.
- ASCII-based sparkline charts for visual load history.

## Setup Instructions

### 1. Install Dependencies
You need Python 3 installed. Open a terminal or command prompt and run:
```bash
cd path/to/kindle-monitor
pip install -r requirements.txt
```

### 2. Running the Server
Start the dashboard server by running:
```bash
python app.py
```
*Note for temperature sensors:* On some OS (like Windows or Linux), you might need to run the command prompt as an Administrator (or use `sudo` on Linux) for the `psutil` sensors to successfully access CPU temperature.
*Note for macOS users:* CPU temperature sensors and NVIDIA GPUs might not be exposed natively. The server will gracefully handle this by displaying "N/A".

### 3. Finding Your Local IP Address
To access the dashboard from your Kindle, they must both be on the same WiFi network.
- **Windows:** Open Command Prompt and type `ipconfig`. Look for the "IPv4 Address" (e.g., `192.168.1.15`).
- **macOS:** Open Terminal and type `ipconfig getifaddr en0` or check Network in System Preferences.
- **Linux:** Open Terminal and type `hostname -I`.

### 4. Connect Your Kindle
1. Connect your Kindle Paperwhite to the same WiFi network as your PC.
2. On your Kindle, tap the three dots in the top right and select **Web Browser**.
3. Type your PC's IP address and port into the URL bar. For example:
   `http://192.168.1.15:5000`
4. The dashboard will load and update automatically every 3 seconds!

### 5. Display Preferences
You can toggle between Dark Mode and Light Mode depending on your preference using the button on the dashboard. The selection will be saved locally on your Kindle.
