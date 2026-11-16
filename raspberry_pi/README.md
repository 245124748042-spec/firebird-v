# Raspberry Pi telemetry forwarding

The laptop backend already owns the dashboard REST and WebSocket services. This forwarder relays each original FireBird `$FB` line over the local Wi-Fi network to that backend; it does not change the firmware protocol or read the webcam.

On the laptop, the backend `.env` must contain `RASPBERRY_PI_MODE=true`, an empty `SERIAL_PORT=`, `HOST=0.0.0.0`, and `PORT=8000`. Start the one existing backend instance with `cd backend; python main.py`. Pi mode skips the laptop serial connection completely. Keep both devices on the same Wi-Fi network and allow inbound TCP port 8000 in the laptop firewall if prompted. The dashboard remains at `http://localhost:5173` and continues to use the same API and WebSocket paths.

On Raspberry Pi OS, install pyserial if needed and run:

From PowerShell on the laptop, copy the sender to the Pi (replace `<PI_IP>` with the Pi's address from `hostname -I`):

```powershell
scp .\raspberry_pi\telemetry_forwarder.py pi@<PI_IP>:/home/pi/person_detection/telemetry_forwarder.py
```

On the Pi, run:

```sh
python3 -m venv ~/firebird-bridge-venv
source ~/firebird-bridge-venv/bin/activate
python -m pip install pyserial
python /home/pi/person_detection/telemetry_forwarder.py --port /dev/ttyUSB0 --baud 9600 --backend http://192.168.62.175:8000 --person-count-file /home/pi/person_detection/person_count.txt
```

The forwarder defaults to `/home/pi/person_detection/person_count.txt` and only sends the count when that file was updated within the last three seconds. If it is missing or stale, the backend shows **Waiting for YOLO** instead of presenting the FireBird frame's `persons` field as a YOLO result. The forwarder does not run inference itself.

The Pi inference script is not present in this repository, so its process state, webcam capture, ONNX loading and launch command cannot be verified or safely guessed here. Its stabilized count branch must refresh the file while inference is running. Use an atomic replacement to prevent partial reads:

```python
from pathlib import Path
tmp = Path('/home/pi/person_detection/person_count.txt.tmp')
tmp.write_text(str(stable_person_count), encoding='utf-8')
tmp.replace('/home/pi/person_detection/person_count.txt')
```

The backend validates each frame with its existing parser and maps the current documented `$FB` format by name/order: `ms`, `ir1..ir5`, `temp_x10`, `hum_x10`, `smoke`, `env_risk`, `total_risk`, `persons`, `dir`, `speed`, `dht_ok`, `flags`. Temperature and humidity remain tenths in telemetry and are displayed divided by ten; `ir1..ir5` are retained as five raw readings. The Pi receive timestamp is attached by the backend. After three seconds without valid Pi frames, the backend returns to simulation mode.

The forwarder accepts only one serial reader on `/dev/ttyUSB0`. Stop any existing script/terminal that already owns the FireBird port before starting it. If the detector itself reads the serial port, combine the forwarding request with that reader instead of opening a second reader. The backend also exposes `POST /api/raspberry-pi/person-count` for count-only updates. The Pi camera stream itself is not proxied by this telemetry bridge.

Check `GET http://<laptop-ip>:8000/api/status` for `mode: LIVE`, `dataSource: LIVE_PI`, and `raspberryPi.connected: true`. `GET /api/telemetry` shows latest parsed readings and forwarded raw lines. The dashboard switches automatically to this live source over its existing WebSocket or REST polling connection.

