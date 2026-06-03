# HIBA UDP Monitor

Prototype UDP monitor for Inovance HIBA-10 packets.

## What it does

- Listens for UDP packets on `0.0.0.0:5010`.
- Accepts packets from `192.168.0.150`.
- Decodes up to 16 HIBA device slots from the 270-byte payload.
- Each device slot contains 8 little-endian 16-bit channels.
- Can decode each channel as unsigned `uint16` or signed `int16`.
- Serves a Flask dashboard with auto-refreshing data.
- Shows active/inactive device slots and channels.
- Provides a separate charts page at `/charts`.
- Provides a configuration page at `/config` for devices, tags, scales, units, signedness, and alarm limits.
- Provides an event/alarm log at `/events`.
- Provides a diagnostics page at `/diagnostics` with packet header, validation, and raw HEX.
- Provides dashboard filters by device state, channel state, quantity, and raw type.
- Supports in-memory chart annotations for starts, parameter changes, faults, stops, and events.
- Tracks per-channel quality and threshold alarm state.
- Lets you select per-channel display formatting in the browser.
- Logs decoded packets to `logs/hiba_log.csv`.
- Keeps graph history and CSV logging throttled so high-rate UDP traffic does not flood the UI or disk.

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
templates/charts.html
templates/config.html
templates/events.html
templates/diagnostics.html
static/style.css
logs/.gitkeep
```

## Setup

```powershell
python -m venv .venv-1
.\.venv-1\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
.\.venv-1\Scripts\python.exe app.py
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
- `GET /api/history` - recent decoded packets, filterable by `device`, `channels`, and `limit`
- `GET /charts` - separate trend chart window
- `GET /config` - edit device and channel configuration
- `GET /events` - threshold event/alarm log
- `GET /diagnostics` - raw packet diagnostics
- `GET /api/config` - current device/channel configuration
- `POST /api/config` - save device/channel configuration to `config.yaml`
- `GET /api/annotations` - chart annotations
- `POST /api/annotations` - add a chart annotation
- `GET /api/events` - threshold event/alarm log as JSON
- `GET /api/diagnostics` - latest raw packet diagnostics as JSON

## Packet Layout

The current prototype uses this layout, confirmed from the provided packet capture:

```text
bytes 0..11      header
bytes 12..267    16 device slots, 16 bytes per device
bytes 268..269   trailer
```

Each device slot contains 8 channels:

```text
device 1 channel 1: bytes 12-13
device 1 channel 8: bytes 26-27
device 2 channel 1: bytes 28-29
...
device 16 channel 8: bytes 266-267
```

A device slot is marked active when at least one of its 8 raw channel words is non-zero. This avoids treating a real zero current as a disconnected channel when the device has other live values.

## Channel Configuration

Edit `config.yaml` or use the `/config` page to set devices and channels:

```yaml
devices:
  - name: MD880_1
    model: MD880
    enabled: true
channels:
  - name: DC bus voltage filter
    tag: DC_BUS_VOLTAGE_FILTER_1
    parameter: U5-05
    scale: 0.1
    unit: V
    signed: false
    warning_low: 450.0
    warning_high: 650.0
    alarm_low: 400.0
    alarm_high: 700.0
```

Decoded value is calculated as:

```text
value = raw * scale
```

For example, `raw / 10` is configured as `scale: 0.1`.

Use `signed: false` for `uint16` and `signed: true` for `int16`.

Signedness cannot be detected reliably from the two bytes alone. The same bytes have different meanings depending on the parameter definition. For example, `FF FF` is `65535` as `uint16` and `-1` as `int16`.

`tag` is the stable technical name used by the dashboard, event log, API, CSV, and future integrations. `parameter` is the drive parameter code, for example `U5-05` or `U6-63`.

Threshold fields are optional:

- `warning_low` / `warning_high` create warning events.
- `alarm_low` / `alarm_high` create alarm events.
- Empty values disable that threshold.

The event log records state changes, not every packet. For example, if a value crosses into `alarm_high`, one alarm event is stored; when it returns to normal, an `alarm_cleared` event is stored.

Channel 8 is currently configured as signed beta current:

```yaml
  - name: Beta current
    parameter: U6-63
    scale: 1.0
    unit: A
    signed: true
```

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

The Type dropdown on the dashboard can reinterpret a channel as Config, `uint16`, or `int16` for quick experiments. For permanent decoding and CSV logging, set `signed` correctly in `config.yaml`.

The dashboard also has filters for:

- Device state: all, active, inactive
- Channel state: all, active, inactive
- Quantity: config, voltage, resistance, current, power, temperature, percent, seconds, custom
- Raw type: config, `uint16`, `int16`

## Event / Alarm Log

Open:

```text
http://localhost:5000/events
```

This page shows threshold transitions with severity, device, tag, value, unit, and timestamp. Events are stored in memory for the current run.

## Diagnostics

Open:

```text
http://localhost:5000/diagnostics
```

This page is the Wireshark-like view for the latest packet. It shows:

- source IP
- packet count
- actual and expected packet length
- header bytes
- start marker
- length field from the header
- trailer bytes
- validation status
- full raw packet HEX

## CSV Logging

Decoded packets are appended to:

```text
logs/hiba_log.csv
```

The CSV contains device activity plus each channel raw value, decoded value, unit, parameter, tag, quality, and alarm state.

The UDP receiver still processes every packet, but CSV logging is intentionally sampled. By default it writes at most once per second. This keeps the file useful for quick inspection without turning a high-rate UDP stream into a huge disk log.

The CSV file is also capped at 5 KB in this prototype. When the cap is reached, the logger keeps the newest compact rows.

## Sampling Rates

The current prototype uses these rates:

- UDP receive: every accepted packet.
- Latest dashboard value: every accepted packet in memory.
- Graph history: at most one sample every 0.2 seconds, about 5 points per second.
- CSV logging: at most one write per second.
- Event/alarm log: every packet is checked, but events are stored only when the state changes.

These values are configured in `app.py`:

```python
DataStore(history_sample_interval_seconds=0.2)
CsvLogger(sample_interval_seconds=1.0)
```

## Charts

Open:

```text
http://localhost:5000/charts
```

The charts page reads filtered history from `/api/history`, so it can draw selected channels for a selected device without downloading all 16 device slots every refresh.

The charts page also supports annotations. They are stored in memory for the current run and can mark motor starts, parameter changes, faults, stops, or custom events.
