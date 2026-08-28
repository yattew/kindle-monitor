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
            import subprocess
            creation_flags = 0
            if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                creation_flags = subprocess.CREATE_NO_WINDOW
                
            # Try OpenHardwareMonitor first, then fallbacks
            ohm_query = "Get-WmiObject -Namespace root\\OpenHardwareMonitor -Class Sensor | Where-Object { $_.SensorType -eq 'Temperature' -and $_.Name -match 'CPU' } | Select-Object -First 1 -ExpandProperty Value"
            
            try:
                cmd = ["powershell", "-NoProfile", "-Command", ohm_query]
                output = subprocess.check_output(cmd, text=True, timeout=2, creationflags=creation_flags).strip()
                if output and output.replace('.', '', 1).isdigit():
                    return f"{float(output):.1f}°C"
            except Exception:
                pass
                
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
        
        /* Legacy WebKit Flexbox for older Kindles */
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-orient: vertical;
        -webkit-box-direction: normal;
        -webkit-flex-direction: column;
        flex-direction: column;
        
        overflow: hidden;
        font-size: {{ FONT_SIZE_BODY }};
        line-height: 1.3;
    }
    .card {
        border: 2px solid #ffffff;
        margin-bottom: 12px;
        padding: 15px;
        box-sizing: border-box;
        
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-pack: justify;
        -webkit-justify-content: space-between;
        justify-content: space-between;
        
        /* Flex grow to fill vertical space */
        -webkit-box-flex: 1;
        -webkit-flex: 1;
        flex: 1;
    }
    .card:last-child {
        margin-bottom: 0; /* Remove bottom margin for the last card to fit perfectly */
    }
    .card-content {
        flex: 1;
        padding-right: 15px;
        
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-orient: vertical;
        -webkit-box-direction: normal;
        -webkit-flex-direction: column;
        flex-direction: column;
        
        -webkit-box-pack: center;
        -webkit-justify-content: center;
        justify-content: center;
    }
    .meter-container {
        width: 60px; /* Made even wider */
        border: 2px solid #ffffff;
        background-color: #000000;
        
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-align: end;
        -webkit-align-items: flex-end;
        align-items: flex-end;
    }
    .meter-fill {
        width: 100%;
        background-color: #ffffff;
    }
    .card-title {
        font-weight: {{ FONT_WEIGHT_TITLE }};
        font-size: {{ FONT_SIZE_TITLE }};
        margin-bottom: 15px;
        border-bottom: 2px dashed #ffffff;
        padding-bottom: 8px;
        text-transform: uppercase;
    }
    .row {
        display: -webkit-box;
        display: -webkit-flex;
        display: flex;
        -webkit-box-pack: justify;
        -webkit-justify-content: space-between;
        justify-content: space-between;
        margin-bottom: 10px;
    }
    .val {
        font-weight: {{ FONT_WEIGHT_TITLE }};
    }
    .hidden {
        display: none !important;
    }
</style>
</head>
<body id="body">
    
    <div class="card" id="cpu_card">
        <div class="card-content">
            <div class="card-title">CPU</div>
            <div class="row"><span>LOAD</span> <span class="val" id="cpu_overall">--%</span></div>
            <div class="row hidden" id="cpu_temp_row"><span>TEMP</span> <span class="val" id="cpu_temp">--°C</span></div>
        </div>
        <div class="meter-container">
            <div class="meter-fill" id="cpu_meter" style="height: 0%;"></div>
        </div>
    </div>
    
    <div class="card" id="ram_card">
        <div class="card-content">
            <div class="card-title">RAM</div>
            <div class="row"><span>LOAD</span> <span class="val" id="ram_percent">--%</span></div>
            <div class="row"><span>USED</span> <span class="val" id="ram_used_total">-- / --GB</span></div>
        </div>
        <div class="meter-container">
            <div class="meter-fill" id="ram_meter" style="height: 0%;"></div>
        </div>
    </div>
    
    <div class="card hidden" id="gpu_card">
        <div class="card-content">
            <div class="card-title">GPU</div>
            <div class="row"><span>LOAD</span> <span class="val" id="gpu_usage">--%</span></div>
            <div class="row"><span>VRAM</span> <span class="val" id="gpu_vram">--GB / --GB</span></div>
            <div class="row"><span>TEMP</span> <span class="val" id="gpu_temp">--°C</span></div>
        </div>
        <div class="meter-container">
            <div class="meter-fill" id="gpu_meter" style="height: 0%;"></div>
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
                    document.getElementById('cpu_meter').style.height = data.cpu_raw_percent + '%';
                    
                    if (data.cpu_temp) {
                        document.getElementById('cpu_temp').innerText = data.cpu_temp;
                        document.getElementById('cpu_temp_row').classList.remove('hidden');
                    } else {
                        document.getElementById('cpu_temp_row').classList.add('hidden');
                    }
                    
                    // Update RAM
                    document.getElementById('ram_percent').innerText = data.ram_percent;
                    document.getElementById('ram_meter').style.height = data.ram_raw_percent + '%';
                    document.getElementById('ram_used_total').innerText = data.ram_used + ' / ' + data.ram_total;
                    
                    // Update GPU
                    if (data.gpu) {
                        document.getElementById('gpu_usage').innerText = data.gpu.usage;
                        document.getElementById('gpu_meter').style.height = data.gpu.raw_percent + '%';
                        document.getElementById('gpu_vram').innerText = data.gpu.vram_used + ' / ' + data.gpu.vram_total;
                        document.getElementById('gpu_temp').innerText = data.gpu.temp;
                        document.getElementById('gpu_card').classList.remove('hidden');
                    } else {
                        document.getElementById('gpu_card').classList.add('hidden');
                    }
                }
            };
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
        "cpu_raw_percent": latest_data['cpu_percent'],
        "cpu_temp": latest_data["cpu_temp"],
        "ram_percent": f"{latest_data['ram_percent']:.1f}%",
        "ram_raw_percent": latest_data['ram_percent'],
        "ram_used": f"{latest_data['ram_used']:.1f}GB",
        "ram_total": f"{latest_data['ram_total']:.1f}GB",
        "gpu": latest_data["gpu_data"]
    })

if __name__ == '__main__':
    t = threading.Thread(target=bg_monitor, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, threaded=True)
