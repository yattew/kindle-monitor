import os
import time
import platform
import threading
from flask import Flask, render_template_string, jsonify
import psutil

# --- CONFIGURATION CONSTANTS ---
REFRESH_RATE_SECONDS = 0.3
FONT_FAMILY = "monospace, sans-serif"
FONT_WEIGHT_BODY = "600"   # 400 is normal, 600 is semi-bold, 700 is bold
FONT_WEIGHT_TITLE = "900"  # 900 is ultra-bold
FONT_SIZE_BODY = "38px"
FONT_SIZE_TITLE = "46px"
# -------------------------------

app = Flask(__name__)

try:
    import GPUtil
    GPU_AVAILABLE = True
except ImportError:
    GPU_AVAILABLE = False

latest_data = {
    "cpu_percent": 0.0,
    "cpu_temp": None,
    "ram_percent": 0.0,
    "ram_used": 0.0,
    "ram_total": 0.0,
    "gpu_data": None
}

def get_cpu_temp():
    try:
        if platform.system() == "Windows":
            # 1. Try LibreHardwareMonitor Web Server (Port 8085)
            try:
                import urllib.request
                import json
                req = urllib.request.Request("http://localhost:8085/data.json")
                with urllib.request.urlopen(req, timeout=1) as response:
                    data = json.loads(response.read().decode())
                    
                    def find_cpu_temp(node):
                        if str(node.get("Type")) == "Temperature":
                            name = str(node.get("Text") or node.get("Name") or "").lower()
                            if "cpu" in name or "tctl" in name or "tdie" in name or "core" in name or "package" in name:
                                val_str = str(node.get("Value", "")).split()[0].replace(',', '.')
                                if val_str.replace('.', '', 1).isdigit():
                                    return float(val_str)
                        
                        best = None
                        for child in node.get("Children", []):
                            res = find_cpu_temp(child)
                            if res is not None:
                                child_name = str(child.get("Text") or child.get("Name") or "").lower()
                                if "package" in child_name or "tctl" in child_name:
                                    return res
                                if best is None:
                                    best = res
                        return best

                    val = find_cpu_temp(data)
                    if val is not None:
                        return f"{val:.1f}°C"
            except Exception:
                pass

            import subprocess
            import json
            creation_flags = 0
            if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                creation_flags = subprocess.CREATE_NO_WINDOW
                
            # 2. Check LibreHardwareMonitor/OpenHardwareMonitor WMI via JSON
            ohm_queries = [
                "Get-WmiObject -Namespace root\\LibreHardwareMonitor -Class Sensor | Where-Object { $_.SensorType -eq 'Temperature' } | Select-Object Identifier, Name, Value | ConvertTo-Json",
                "Get-WmiObject -Namespace root\\OpenHardwareMonitor -Class Sensor | Where-Object { $_.SensorType -eq 'Temperature' } | Select-Object Identifier, Name, Value | ConvertTo-Json"
            ]
            
            for ohm_query in ohm_queries:
                try:
                    cmd = ["powershell", "-NoProfile", "-Command", ohm_query]
                    output = subprocess.check_output(cmd, text=True, timeout=2, creationflags=creation_flags).strip()
                    if output:
                        sensors = json.loads(output)
                        if isinstance(sensors, dict):
                            sensors = [sensors]
                            
                        best_temp = None
                        for s in sensors:
                            ident = str(s.get("Identifier") or "").lower()
                            name = str(s.get("Name") or "").lower()
                            val = s.get("Value")
                            
                            if val is None:
                                continue
                                
                            if "cpu" in ident or "cpu" in name or "tctl" in name or "tdie" in name or "core" in name or "package" in name:
                                if "package" in name or "tctl" in name:
                                    return f"{float(val):.1f}°C"
                                if best_temp is None:
                                    best_temp = float(val)
                                    
                        if best_temp is not None:
                            return f"{best_temp:.1f}°C"
                except Exception:
                    continue
                
            # 3. Final fallback to standard ACPI WMI
            queries = [
                "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature | Select-Object -ExpandProperty CurrentTemperature",
                "Get-WmiObject Win32_PerfFormattedData_Counters_ThermalZoneInformation | Select-Object -ExpandProperty HighPrecisionTemperature"
            ]
            
            for q in queries:
                try:
                    cmd = ["powershell", "-NoProfile", "-Command", q]
                    output = subprocess.check_output(cmd, text=True, timeout=2, creationflags=creation_flags).strip()
                    if output:
                        for line in output.split('\\n'):
                            val = line.strip()
                            if val.isdigit():
                                celsius = (int(val) / 10.0) - 273.15
                                if 0 < celsius < 150:
                                    return f"{celsius:.1f}°C"
                except Exception:
                    continue
            return None
            
        # Linux/macOS fallback
        temps = psutil.sensors_temperatures()
        if not temps:
            return None
        for name, entries in temps.items():
            if name.startswith('coretemp') or name.startswith('cpu'):
                for entry in entries:
                    return f"{entry.current:.1f}°C"
        first = list(temps.values())[0][0]
        return f"{first.current:.1f}°C"
    except Exception:
        return None

def get_gpu_data():
    if not GPU_AVAILABLE:
        return None
    try:
        gpus = GPUtil.getGPUs()
        if gpus:
            gpu = gpus[0]
            return {
                "usage": f"{gpu.load * 100:.1f}%",
                "raw_percent": gpu.load * 100,
                "vram_used": f"{gpu.memoryUsed / 1024.0:.1f}GB",
                "vram_total": f"{gpu.memoryTotal / 1024.0:.1f}GB",
                "temp": f"{gpu.temperature}°C"
            }
        return None
    except Exception:
        return None

def bg_monitor():
    psutil.cpu_percent(interval=None)
    time.sleep(1)
    
    while True:
        try:
            cpu_p = psutil.cpu_percent(interval=None)
            cpu_t = get_cpu_temp()
            
            ram = psutil.virtual_memory()
            gpu = get_gpu_data()
            
            latest_data["cpu_percent"] = cpu_p
            latest_data["cpu_temp"] = cpu_t
            
            latest_data["ram_percent"] = ram.percent
            latest_data["ram_used"] = ram.used / (1024 ** 3)
            latest_data["ram_total"] = ram.total / (1024 ** 3)
            latest_data["gpu_data"] = gpu
        except Exception as e:
            print("Error in background monitor:", e)
        
        time.sleep(REFRESH_RATE_SECONDS)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kindle Monitor</title>
<style>
    html, body {
        height: 100%;
        margin: 0;
        padding: 0;
    }
    body {
        background-color: #000000; 
        color: #ffffff; 
        font-family: {{ FONT_FAMILY }}; 
        font-weight: {{ FONT_WEIGHT_BODY }};
        padding: 12px;
        box-sizing: border-box;
        
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-orient: vertical;
        -webkit-box-direction: normal;
        -webkit-flex-direction: column;
        flex-direction: column;
        
        overflow: hidden;
        line-height: 1.2;
    }
    
    /* --- TOP SECTION: MONITORS --- */
    .monitor-container {
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-orient: vertical;
        -webkit-flex-direction: column;
        flex-direction: column;
        margin-bottom: 20px;
        border-bottom: 2px dashed #555;
        padding-bottom: 15px;
    }
    .tiny-card {
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-pack: justify;
        -webkit-justify-content: space-between;
        justify-content: space-between;
        font-size: 24px;
        margin-bottom: 8px;
    }
    .tiny-title {
        font-weight: {{ FONT_WEIGHT_TITLE }};
        color: #aaa;
        width: 60px;
    }
    .tiny-val {
        font-weight: bold;
    }
    .hidden {
        display: none !important;
    }
    
    /* --- BOTTOM SECTION: MEDIA --- */
    .media-container {
        -webkit-box-flex: 1;
        -webkit-flex: 1;
        flex: 1;
        
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-orient: vertical;
        -webkit-flex-direction: column;
        flex-direction: column;
        
        -webkit-box-align: center;
        -webkit-align-items: center;
        align-items: center;
        -webkit-box-pack: end;
        -webkit-justify-content: flex-end;
        justify-content: flex-end;
    }
    .album-art {
        width: 300px;
        height: 300px;
        border: 2px solid #555;
        margin-bottom: 15px;
        background-color: #111;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #555;
        font-size: 20px;
    }
    .album-art img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
    .media-title {
        font-size: 28px;
        font-weight: bold;
        text-align: center;
        margin-bottom: 25px;
        width: 100%;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .media-controls {
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-pack: center;
        -webkit-justify-content: center;
        justify-content: center;
        width: 100%;
        margin-bottom: 30px;
    }
    .media-btn {
        background: transparent;
        color: #fff;
        border: 2px solid #fff;
        font-size: 32px;
        padding: 15px 35px;
        margin: 0 10px;
        cursor: pointer;
    }
    .media-btn:active {
        background: #fff;
        color: #000;
    }
    
    /* --- VOLUME SLIDER --- */
    .slider-container {
        width: 100%;
        display: flex;
        align-items: center;
        margin-bottom: 10px;
    }
    .vol-icon {
        font-size: 24px;
        margin-right: 15px;
    }
    .vol-slider {
        -webkit-appearance: none;
        width: 100%;
        height: 8px;
        background: #555;
        outline: none;
        border-radius: 4px;
    }
    .vol-slider::-webkit-slider-thumb {
        -webkit-appearance: none;
        width: 30px;
        height: 30px;
        background: #fff;
        border-radius: 50%;
        cursor: pointer;
    }
</style>
</head>
<body id="body">
    
    <!-- TOP SECTION: HARDWARE MONITORS -->
    <div class="monitor-container">
        <div class="tiny-card" id="cpu_card">
            <span class="tiny-title">CPU</span>
            <span class="tiny-val" id="cpu_overall">--%</span>
            <span class="tiny-val hidden" id="cpu_temp">--°C</span>
        </div>
        <div class="tiny-card" id="ram_card">
            <span class="tiny-title">RAM</span>
            <span class="tiny-val" id="ram_percent">--%</span>
            <span class="tiny-val" id="ram_used_total">--GB</span>
        </div>
        <div class="tiny-card hidden" id="gpu_card">
            <span class="tiny-title">GPU</span>
            <span class="tiny-val" id="gpu_usage">--%</span>
            <span class="tiny-val" id="gpu_vram">--GB</span>
            <span class="tiny-val" id="gpu_temp">--°C</span>
        </div>
    </div>
    
    <!-- BOTTOM SECTION: MEDIA CONTROLS -->
    <div class="media-container">
        <div class="album-art">
            <img id="album_img" src="" alt="No Art" style="display: none;">
            <span id="album_placeholder">No Media</span>
        </div>
        
        <div class="media-title" id="media_title">Awaiting Media...</div>
        
        <div class="media-controls">
            <button class="media-btn" onclick="sendMediaCmd('prev')">⏮</button>
            <button class="media-btn" onclick="sendMediaCmd('playpause')">⏯</button>
            <button class="media-btn" onclick="sendMediaCmd('next')">⏭</button>
        </div>
        
        <div class="slider-container">
            <span class="vol-icon">🔉</span>
            <input type="range" min="0" max="100" value="50" class="vol-slider" id="vol_slider" onchange="setVolume(this.value)">
        </div>
    </div>

    <script>
        function updateData() {
            var xhr = new XMLHttpRequest();
            xhr.open('GET', '/data', true);
            xhr.onload = function() {
                if (xhr.status === 200) {
                    var data = JSON.parse(xhr.responseText);
                    
                    // Update CPU
                    document.getElementById('cpu_overall').innerText = data.cpu_overall;
                    if (data.cpu_temp) {
                        document.getElementById('cpu_temp').innerText = data.cpu_temp;
                        document.getElementById('cpu_temp').classList.remove('hidden');
                    }
                    
                    // Update RAM
                    document.getElementById('ram_percent').innerText = data.ram_percent;
                    document.getElementById('ram_used_total').innerText = data.ram_used + ' / ' + data.ram_total;
                    
                    // Update GPU
                    if (data.gpu) {
                        document.getElementById('gpu_usage').innerText = data.gpu.usage;
                        document.getElementById('gpu_vram').innerText = data.gpu.vram_used + ' / ' + data.gpu.vram_total;
                        document.getElementById('gpu_temp').innerText = data.gpu.temp;
                        document.getElementById('gpu_card').classList.remove('hidden');
                    }
                }
            };
            xhr.send();
        }

        function sendMediaCmd(cmd) {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/media_cmd?cmd=' + cmd, true);
            xhr.send();
        }

        function setVolume(val) {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/set_vol?level=' + val, true);
            xhr.send();
        }

        updateData();
        setInterval(updateData, {{ REFRESH_RATE_MS }});
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE, 
        FONT_FAMILY=FONT_FAMILY,
        FONT_WEIGHT_BODY=FONT_WEIGHT_BODY,
        FONT_WEIGHT_TITLE=FONT_WEIGHT_TITLE,
        FONT_SIZE_BODY=FONT_SIZE_BODY,
        FONT_SIZE_TITLE=FONT_SIZE_TITLE,
        REFRESH_RATE_MS=int(REFRESH_RATE_SECONDS * 1000)
    )

@app.route('/data')
def data():
    return jsonify({
        "cpu_overall": f"{latest_data['cpu_percent']:.1f}%",
        "cpu_temp": latest_data["cpu_temp"],
        "ram_percent": f"{latest_data['ram_percent']:.1f}%",
        "ram_used": f"{latest_data['ram_used']:.1f}GB",
        "ram_total": f"{latest_data['ram_total']:.1f}GB",
        "gpu": latest_data["gpu_data"]
    })

@app.route('/media_cmd', methods=['POST'])
def media_cmd():
    cmd = request.args.get('cmd')
    if platform.system() == "Windows":
        import ctypes
        # VK_MEDIA_NEXT_TRACK = 0xB0, VK_MEDIA_PREV_TRACK = 0xB1, VK_MEDIA_PLAY_PAUSE = 0xB3
        keys = {'next': 0xB0, 'prev': 0xB1, 'playpause': 0xB3}
        if cmd in keys:
            vk = keys[cmd]
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0) # Key Down
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0) # Key Up
    return jsonify({"status": "ok"})

@app.route('/set_vol', methods=['POST'])
def set_vol():
    level = request.args.get('level', type=int)
    print(f"Set volume requested: {level}%")
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    t = threading.Thread(target=bg_monitor, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, threaded=True)
