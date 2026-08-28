import os
import time
import platform
import threading
from flask import Flask, render_template_string, jsonify, request
import psutil

# --- CONFIGURATION CONSTANTS ---
REFRESH_RATE_SECONDS = 0.3
FONT_FAMILY = "monospace, sans-serif"
FONT_WEIGHT_BODY = "600"   # 400 is normal, 600 is semi-bold, 700 is bold
FONT_WEIGHT_TITLE = "900"  # 900 is ultra-bold
FONT_SIZE_BODY = "22px"
FONT_SIZE_TITLE = "28px"
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
    "gpu_data": None,
    "media": None,
    "volume": 50
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
    /* Reset & Base */
    html, body {
        height: 100%;
        margin: 0;
        padding: 0;
        background-color: #000000; 
        color: #ffffff; 
        font-family: {{ FONT_FAMILY }}; 
        font-weight: {{ FONT_WEIGHT_BODY }};
        overflow: hidden;
        line-height: 1.2;
    }
    .main-container {
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-orient: vertical;
        -webkit-box-direction: normal;
        -webkit-flex-direction: column;
        flex-direction: column;
        height: 100%;
        padding: 15px;
        box-sizing: border-box;
    }

    /* --- TOP SECTION (3 Monitors) --- */
    .top-section {
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-flex: 1;
        -webkit-flex: 1;
        flex: 1;
        margin-bottom: 20px;
    }
    .card {
        border: 4px solid #ffffff;
        border-radius: 25px;
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-orient: vertical;
        -webkit-flex-direction: column;
        flex-direction: column;
        -webkit-box-flex: 1;
        -webkit-flex: 1;
        flex: 1;
        margin-right: 15px;
        padding: 15px;
        -webkit-box-align: center;
        -webkit-align-items: center;
        align-items: center;
        -webkit-box-pack: start;
        -webkit-justify-content: flex-start;
        justify-content: flex-start;
    }
    .card:last-child {
        margin-right: 0;
    }
    .card-title {
        font-weight: {{ FONT_WEIGHT_TITLE }};
        font-size: {{ FONT_SIZE_TITLE }};
        margin-bottom: 25px;
        text-align: center;
        width: 100%;
    }
    .card-val {
        font-size: {{ FONT_SIZE_BODY }};
        margin-bottom: 15px;
        text-align: center;
    }
    .hidden {
        display: none !important;
    }

    /* --- MIDDLE SECTION (Media Player) --- */
    .middle-section {
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        height: 32%; /* Take up roughly a third of the screen */
        margin-bottom: 20px;
    }
    .album-art {
        border: 4px solid #ffffff;
        border-radius: 25px;
        width: 40%; /* Fixed width relative to parent */
        margin-right: 15px;
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-align: center;
        -webkit-align-items: center;
        align-items: center;
        -webkit-box-pack: center;
        -webkit-justify-content: center;
        justify-content: center;
        overflow: hidden;
    }
    .album-art img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
    .media-info {
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-orient: vertical;
        -webkit-flex-direction: column;
        flex-direction: column;
        -webkit-box-flex: 1;
        -webkit-flex: 1;
        flex: 1;
    }
    .media-title {
        border: 4px solid #ffffff;
        border-radius: 25px;
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-align: center;
        -webkit-align-items: center;
        align-items: center;
        -webkit-box-pack: center;
        -webkit-justify-content: center;
        justify-content: center;
        font-size: {{ FONT_SIZE_TITLE }};
        font-weight: {{ FONT_WEIGHT_TITLE }};
        margin-bottom: 15px;
        padding: 10px;
        text-align: center;
        -webkit-box-flex: 1;
        -webkit-flex: 1;
        flex: 1; /* take remaining height */
    }
    .media-buttons {
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        height: 45%;
    }
    .media-btn {
        border: 4px solid #ffffff;
        border-radius: 15px;
        background: transparent;
        color: #ffffff;
        font-size: 45px;
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-align: center;
        -webkit-align-items: center;
        align-items: center;
        -webkit-box-pack: center;
        -webkit-justify-content: center;
        justify-content: center;
        -webkit-box-flex: 1;
        -webkit-flex: 1;
        flex: 1;
        margin-right: 15px;
        cursor: pointer;
    }
    .media-btn:active {
        background: #ffffff;
        color: #000000;
    }
    .media-btn:last-child {
        margin-right: 0;
    }

    /* --- BOTTOM SECTION (Volume Slider) --- */
    .bottom-section {
        border: 4px solid #ffffff;
        border-radius: 15px;
        padding: 0 20px;
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-align: center;
        -webkit-align-items: center;
        align-items: center;
        -webkit-box-pack: center;
        -webkit-justify-content: center;
        justify-content: center;
        height: 80px; /* Fixed tall height for bottom slider container */
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
        width: 50px;
        height: 50px;
        background: #ffffff;
        border-radius: 10px;
        cursor: pointer;
    }
</style>
</head>
<body id="body">
    <div class="main-container">
        
        <!-- TOP SECTION: 3 Columns -->
        <div class="top-section">
            <div class="card" id="cpu_card">
                <div class="card-title">CPU</div>
                <div class="card-val" id="cpu_overall">--%</div>
                <div class="card-val hidden" id="cpu_temp">--°C</div>
            </div>
            
            <div class="card" id="gpu_card">
                <div class="card-title">GPU</div>
                <div class="card-val" id="gpu_usage">--%</div>
                <div class="card-val" id="gpu_temp">--°C</div>
                <div class="card-val" id="gpu_vram">--GB</div>
            </div>
            
            <div class="card" id="ram_card">
                <div class="card-title">RAM</div>
                <div class="card-val" id="ram_percent">--%</div>
                <div class="card-val" id="ram_used_total">--GB</div>
            </div>
        </div>
        
        <!-- MIDDLE SECTION: Media -->
        <div class="middle-section">
            <div class="album-art">
                <img id="album_img" src="" alt="Art" style="display: none;">
                <span id="album_placeholder" style="font-size: 32px; font-weight: bold; color: #555;">Art</span>
            </div>
            
            <div class="media-info">
                <div class="media-title" id="media_title">Music Title</div>
                
                <div class="media-buttons">
                    <button class="media-btn" onclick="sendMediaCmd('prev')">⏮</button>
                    <button class="media-btn" onclick="sendMediaCmd('playpause')">⏯</button>
                    <button class="media-btn" onclick="sendMediaCmd('next')">⏭</button>
                </div>
            </div>
        </div>
        
        <!-- BOTTOM SECTION: Volume -->
        <div class="bottom-section">
            <input type="range" min="0" max="100" value="50" class="vol-slider" id="vol_slider" oninput="isDragging=true;" onchange="setVolume(this.value)">
        </div>
        
    </div>

    <script>
        var isDragging = false;

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
                    document.getElementById('ram_used_total').innerText = data.ram_used;
                    
                    // Update GPU
                    if (data.gpu) {
                        document.getElementById('gpu_usage').innerText = data.gpu.usage;
                        document.getElementById('gpu_vram').innerText = data.gpu.vram_used;
                        document.getElementById('gpu_temp').innerText = data.gpu.temp;
                    }
                    
                    // Update Media
                    if (data.media) {
                        document.getElementById('media_title').innerText = data.media.title;
                        if (data.media.art) {
                            document.getElementById('album_img').src = data.media.art;
                            document.getElementById('album_img').style.display = 'block';
                            document.getElementById('album_placeholder').style.display = 'none';
                        } else {
                            document.getElementById('album_img').style.display = 'none';
                            document.getElementById('album_placeholder').style.display = 'block';
                        }
                    } else {
                        document.getElementById('media_title').innerText = "No Media";
                        document.getElementById('album_img').style.display = 'none';
                        document.getElementById('album_placeholder').style.display = 'block';
                    }
                    
                    // Update Volume Slider (only if user is not currently dragging it)
                    if (!isDragging) {
                        document.getElementById('vol_slider').value = data.volume;
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
            xhr.onload = function() {
                isDragging = false; // Reset dragging state when server acknowledges volume change
            }
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
        "gpu": latest_data["gpu_data"],
        "media": latest_data["media"],
        "volume": latest_data["volume"]
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
            # Media keys are 'Extended Keys' in Windows. We must pass 0x0001 (KEYEVENTF_EXTENDEDKEY)
            ctypes.windll.user32.keybd_event(vk, 0, 1, 0)       # Key Down (Extended)
            ctypes.windll.user32.keybd_event(vk, 0, 1 | 2, 0)   # Key Up (Extended + KeyUp)
    return jsonify({"status": "ok"})

@app.route('/set_vol', methods=['POST'])
def set_vol():
    level = request.args.get('level', type=int)
    if level is not None:
        set_master_volume(level)
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    t = threading.Thread(target=bg_monitor, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, threaded=True)
