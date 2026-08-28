import os
import time
import platform
import threading
from collections import deque
from flask import Flask, render_template_string, jsonify
import psutil

app = Flask(__name__)

try:
    import GPUtil
    GPU_AVAILABLE = True
except ImportError:
    GPU_AVAILABLE = False

latest_data = {
    "cpu_percent": 0.0,
    "cpu_per_core": [],
    "cpu_temp": None,
    "ram_percent": 0.0,
    "ram_used": 0.0,
    "ram_total": 0.0,
    "gpu_data": None,
    "cpu_history": deque(maxlen=18),
    "ram_history": deque(maxlen=18)
}

def get_cpu_temp():
    try:
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
                "vram_used": f"{gpu.memoryUsed}MB",
                "vram_total": f"{gpu.memoryTotal}MB",
                "temp": f"{gpu.temperature}°C"
            }
        return None
    except Exception:
        return None

def generate_sparkline(data_points):
    if not data_points:
        return ""
    bars = " ▂▃▄▅▆▇█"
    line = ""
    for val in data_points:
        if val is None:
            line += " "
            continue
        idx = int((val / 100.0) * (len(bars) - 1))
        idx = max(0, min(len(bars) - 1, idx))
        line += bars[idx]
    return line

def generate_progress_bar(percent, length=20):
    if not isinstance(percent, (int, float)):
        return f"[{'░'*length}]"
    filled_length = int(length * percent // 100)
    filled_length = max(0, min(length, filled_length))
    empty_length = length - filled_length
    return f"[{'█'*filled_length}{'░'*empty_length}]"

def bg_monitor():
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)
    time.sleep(1)
    
    while True:
        try:
            cpu_p = psutil.cpu_percent(interval=None)
            cpu_cores = psutil.cpu_percent(interval=None, percpu=True)
            cpu_t = get_cpu_temp()
            
            ram = psutil.virtual_memory()
            gpu = get_gpu_data()
            
            latest_data["cpu_percent"] = cpu_p
            latest_data["cpu_per_core"] = cpu_cores
            latest_data["cpu_temp"] = cpu_t
            
            latest_data["ram_percent"] = ram.percent
            latest_data["ram_used"] = ram.used / (1024 ** 3)
            latest_data["ram_total"] = ram.total / (1024 ** 3)
            latest_data["gpu_data"] = gpu
            
            latest_data["cpu_history"].append(cpu_p)
            latest_data["ram_history"].append(ram.percent)
        except Exception as e:
            print("Error in background monitor:", e)
        
        time.sleep(3)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kindle Monitor</title>
<style>
    body {
        background-color: #000000; 
        color: #ffffff; 
        font-family: monospace; 
        margin: 0;
        padding: 10px;
        font-size: 18px;
        line-height: 1.2;
    }
    .card {
        border: 2px solid #ffffff;
        margin-bottom: 15px;
        padding: 10px;
        box-sizing: border-box;
    }
    .card-title {
        font-weight: bold;
        font-size: 20px;
        margin-bottom: 8px;
        border-bottom: 1px dashed #ffffff;
        padding-bottom: 4px;
        text-transform: uppercase;
    }
    .row {
        display: flex;
        justify-content: space-between;
        margin-bottom: 4px;
    }
    .val {
        font-weight: bold;
    }
    .bar {
        font-size: 16px;
        letter-spacing: -1px;
    }
    .sparkline {
        font-size: 28px;
        letter-spacing: 0px;
        text-align: left;
        line-height: 1;
        margin: 10px 0;
        white-space: pre;
    }
    .cores-grid {
        display: flex;
        flex-wrap: wrap;
        font-size: 14px;
        margin-top: 10px;
        border-top: 1px dashed #ffffff;
        padding-top: 8px;
    }
    .core {
        width: 50%; 
        box-sizing: border-box;
    }
    .hidden {
        display: none !important;
    }
</style>
</head>
<body id="body">
    
    <div class="card" id="cpu_card">
        <div class="card-title">CPU</div>
        <div class="row"><span>LOAD</span> <span class="val" id="cpu_overall">--%</span></div>
        <div class="row bar" id="cpu_bar">[                    ]</div>
        <div class="row hidden" id="cpu_temp_row"><span>TEMP</span> <span class="val" id="cpu_temp">--°C</span></div>
        <div class="sparkline" id="cpu_spark"></div>
        <div class="cores-grid" id="cpu_cores_container"></div>
    </div>
    
    <div class="card" id="ram_card">
        <div class="card-title">RAM</div>
        <div class="row"><span>LOAD</span> <span class="val" id="ram_percent">--%</span></div>
        <div class="row bar" id="ram_bar">[                    ]</div>
        <div class="row"><span>USED</span> <span class="val" id="ram_used_total">-- / --GB</span></div>
        <div class="sparkline" id="ram_spark"></div>
    </div>
    
    <div class="card hidden" id="gpu_card">
        <div class="card-title">GPU</div>
        <div class="row"><span>LOAD</span> <span class="val" id="gpu_usage">--%</span></div>
        <div class="row"><span>VRAM</span> <span class="val" id="gpu_vram">--MB / --MB</span></div>
        <div class="row"><span>TEMP</span> <span class="val" id="gpu_temp">--°C</span></div>
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
                    document.getElementById('cpu_bar').innerText = data.cpu_bar;
                    document.getElementById('cpu_spark').innerText = data.cpu_spark;
                    
                    if (data.cpu_temp) {
                        document.getElementById('cpu_temp').innerText = data.cpu_temp;
                        document.getElementById('cpu_temp_row').classList.remove('hidden');
                    } else {
                        document.getElementById('cpu_temp_row').classList.add('hidden');
                    }
                    
                    var coresHtml = '';
                    for (var i=0; i<data.cpu_cores.length; i++) {
                        var c = i.toString().padStart(2, '0');
                        coresHtml += '<div class="core">C' + c + ':' + data.cpu_cores[i] + '</div>';
                    }
                    document.getElementById('cpu_cores_container').innerHTML = coresHtml;
                    
                    // Update RAM
                    document.getElementById('ram_percent').innerText = data.ram_percent;
                    document.getElementById('ram_bar').innerText = data.ram_bar;
                    document.getElementById('ram_used_total').innerText = data.ram_used + ' / ' + data.ram_total;
                    document.getElementById('ram_spark').innerText = data.ram_spark;
                    
                    // Update GPU
                    if (data.gpu) {
                        document.getElementById('gpu_usage').innerText = data.gpu.usage;
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
        setInterval(updateData, 3000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def data():
    cpu_cores_formatted = [f"{c:5.1f}%" for c in latest_data["cpu_per_core"]]
    
    return jsonify({
        "cpu_overall": f"{latest_data['cpu_percent']:.1f}%",
        "cpu_bar": generate_progress_bar(latest_data['cpu_percent'], 20),
        "cpu_temp": latest_data["cpu_temp"],
        "cpu_cores": cpu_cores_formatted,
        "cpu_spark": generate_sparkline(latest_data["cpu_history"]),
        "ram_percent": f"{latest_data['ram_percent']:.1f}%",
        "ram_bar": generate_progress_bar(latest_data['ram_percent'], 20),
        "ram_used": f"{latest_data['ram_used']:.1f}GB",
        "ram_total": f"{latest_data['ram_total']:.1f}GB",
        "ram_spark": generate_sparkline(latest_data["ram_history"]),
        "gpu": latest_data["gpu_data"]
    })

if __name__ == '__main__':
    t = threading.Thread(target=bg_monitor, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, threaded=True)
