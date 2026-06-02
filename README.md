# HIBA UDP Monitor

Prototype UDP monitor for Inovance HIBA-10 packets.

## What it does

- Listens for UDP packets on `0.0.0.0:5010`.
- Accepts packets from `192.168.0.150`.
- Decodes 8 little-endian `uint16` channels from payload offsets `12..27`.
- Can decode each channel as unsigned `uint16` or signed `int16`.
- Serves a Flask dashboard with auto-refreshing data.
- Lets you select per-channel display formatting in the browser.
- Logs decoded packets to `logs/hiba_log.csv`.

## Project Structure

```text
app.py
hiba_receiver.py
hiba_decoder.py
data_store.py
csv_logger.py
config.yaml
requirements.txt
templates/index.html
static/style.css
logs/.gitkeep
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python app.py
```

Open the dashboard:

```text
http://localhost:5000
```

The UDP receiver runs in a daemon thread while Flask serves the web UI.

## API

- `GET /` - dashboard
- `GET /api/latest` - latest decoded packet
- `GET /api/status` - receiver counters and error state
- `GET /api/history` - recent decoded packets

## Channel Configuration

Edit `config.yaml` to set each channel:

```yaml
channels:
  - name: DC bus voltage filter
    parameter: U5-05
    scale: 0.1
    unit: V
    signed: false
```

Decoded value is calculated as:

```text
value = raw * scale
```

For example, `raw / 10` is configured as `scale: 0.1`.

Use `signed: false` for `uint16` and `signed: true` for `int16`.

## Dashboard Formatting

The server always decodes raw bytes according to `config.yaml`. The dashboard then lets you choose how to display each channel:

- Voltage
- Resistance
- Current
- Power
- Temperature
- Percent
- Seconds
- Custom

The Custom option enables browser-side fields for display name, scale, unit, and decimal places. These dashboard choices are saved in the browser local storage.
