from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

from csv_logger import CsvLogger
from data_store import DataStore
from hiba_decoder import CHANNEL_COUNT, DEVICE_COUNT, ChannelConfig, DeviceConfig
from hiba_receiver import HibaUdpReceiver, load_monitor_config, save_monitor_config


def create_app() -> Flask:
    app = Flask(__name__)

    devices, channels = load_monitor_config("config.yaml")
    store = DataStore(
        history_limit=10000,
        active_timeout_seconds=3.0,
        history_sample_interval_seconds=0.2,
    )
    logger = CsvLogger(
        "logs/hiba_log.csv",
        channels,
        sample_interval_seconds=1.0,
    )

    receiver = HibaUdpReceiver(
        host="0.0.0.0",
        port=5010,
        allowed_source_ip="192.168.0.150",
        devices=devices,
        channels=channels,
        store=store,
        logger=logger,
    )
    receiver.start()

    @app.route("/")
    def index():
        return render_template("index.html", channels=channels, devices=devices)

    @app.route("/charts")
    def charts():
        return render_template("charts.html", channels=channels, devices=devices, max_devices=16)

    @app.route("/config")
    def config_page():
        return render_template("config.html", channels=channels, devices=devices)

    @app.route("/events")
    def events_page():
        return render_template("events.html")

    @app.route("/diagnostics")
    def diagnostics_page():
        return render_template("diagnostics.html")

    @app.route("/api/latest")
    def api_latest():
        return jsonify(store.latest())

    @app.route("/api/status")
    def api_status():
        return jsonify(store.status())

    @app.route("/api/history")
    def api_history():
        limit = _parse_int_arg("limit", default=1000, minimum=1, maximum=5000)
        device_index = _parse_int_arg("device", default=1, minimum=1, maximum=16)
        channel_indexes = _parse_channel_indexes(request.args.get("channels"))
        return jsonify(store.history_for_chart(device_index, channel_indexes, limit=limit))

    @app.route("/api/config", methods=["GET"])
    def api_config():
        return jsonify(
            {
                "devices": [_device_to_dict(device) for device in devices],
                "channels": [_channel_to_dict(channel) for channel in channels],
            }
        )

    @app.route("/api/config", methods=["POST"])
    def api_save_config():
        nonlocal devices, channels
        payload = request.get_json(silent=True) or {}
        try:
            updated_devices = _parse_device_config_payload(payload)
            updated_channels = _parse_channel_config_payload(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        devices = updated_devices
        channels = updated_channels
        receiver.devices = devices
        receiver.channels = channels
        logger.channels = channels
        save_monitor_config("config.yaml", devices, channels)
        return jsonify(
            {
                "devices": [_device_to_dict(device) for device in devices],
                "channels": [_channel_to_dict(channel) for channel in channels],
            }
        )

    @app.route("/api/annotations", methods=["GET"])
    def api_annotations():
        return jsonify({"items": store.annotations()})

    @app.route("/api/events", methods=["GET"])
    def api_events():
        return jsonify({"items": store.events()})

    @app.route("/api/diagnostics", methods=["GET"])
    def api_diagnostics():
        latest = store.latest()
        return jsonify(
            {
                "timestamp": latest.get("timestamp"),
                "source_ip": latest.get("source_ip"),
                "packet_count": latest.get("packet_count"),
                "packet_length": latest.get("packet_length"),
                "expected_packet_length": latest.get("expected_packet_length"),
                "header": latest.get("header", {}),
                "validation": latest.get("validation", {}),
                "raw_packet_hex": latest.get("raw_packet_hex", ""),
            }
        )

    @app.route("/api/annotations", methods=["POST"])
    def api_add_annotation():
        payload = request.get_json(silent=True) or {}
        label = str(payload.get("label", "")).strip()
        if not label:
            return jsonify({"error": "Annotation label is required"}), 400

        annotation = {
            "timestamp": str(
                payload.get("timestamp")
                or datetime.now(timezone.utc).isoformat()
            ),
            "label": label,
            "kind": str(payload.get("kind", "event")),
            "details": str(payload.get("details", "")),
            "device": _optional_int(payload.get("device")),
            "channel": _optional_int(payload.get("channel")),
        }
        return jsonify(store.add_annotation(annotation)), 201

    return app


def _device_to_dict(device: DeviceConfig) -> dict[str, object]:
    return {
        "index": device.index,
        "name": device.name,
        "model": device.model,
        "enabled": device.enabled,
    }


def _channel_to_dict(channel: ChannelConfig) -> dict[str, object]:
    return {
        "index": channel.index,
        "name": channel.name,
        "tag": channel.tag,
        "parameter": channel.parameter,
        "scale": channel.scale,
        "unit": channel.unit,
        "signed": channel.signed,
        "warning_low": channel.warning_low,
        "warning_high": channel.warning_high,
        "alarm_low": channel.alarm_low,
        "alarm_high": channel.alarm_high,
    }


def _parse_device_config_payload(payload: dict[str, object]) -> list[DeviceConfig]:
    raw_devices = payload.get("devices")
    if not isinstance(raw_devices, list):
        raw_devices = []

    devices: list[DeviceConfig] = []
    for index in range(1, DEVICE_COUNT + 1):
        raw_device = (
            raw_devices[index - 1]
            if index - 1 < len(raw_devices) and isinstance(raw_devices[index - 1], dict)
            else {}
        )
        devices.append(
            DeviceConfig(
                index=index,
                name=str(raw_device.get("name", f"MD880_{index}")).strip()
                or f"MD880_{index}",
                model=str(raw_device.get("model", "MD880")).strip() or "MD880",
                enabled=bool(raw_device.get("enabled", True)),
            )
        )
    return devices


def _parse_channel_config_payload(payload: dict[str, object]) -> list[ChannelConfig]:
    raw_channels = payload.get("channels")
    if not isinstance(raw_channels, list) or len(raw_channels) != CHANNEL_COUNT:
        raise ValueError(f"Exactly {CHANNEL_COUNT} channels are required")

    channels: list[ChannelConfig] = []
    for index, raw_channel in enumerate(raw_channels, start=1):
        if not isinstance(raw_channel, dict):
            raise ValueError(f"Channel {index} must be an object")
        try:
            scale = float(raw_channel.get("scale", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Channel {index} scale must be numeric") from exc
        channels.append(
            ChannelConfig(
                index=index,
                name=str(raw_channel.get("name", f"Channel {index}")).strip()
                or f"Channel {index}",
                tag=str(raw_channel.get("tag", f"TAG_{index}")).strip() or f"TAG_{index}",
                parameter=str(raw_channel.get("parameter", "")).strip(),
                scale=scale,
                unit=str(raw_channel.get("unit", "")).strip(),
                signed=bool(raw_channel.get("signed", False)),
                warning_low=_optional_float(raw_channel.get("warning_low")),
                warning_high=_optional_float(raw_channel.get("warning_high")),
                alarm_low=_optional_float(raw_channel.get("alarm_low")),
                alarm_high=_optional_float(raw_channel.get("alarm_high")),
            )
        )
    return channels


def _optional_int(value: object) -> int | None:
    if value in ("", None):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int_arg(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _parse_channel_indexes(raw_value: str | None) -> set[int]:
    if not raw_value:
        return {1}

    indexes: set[int] = set()
    for raw_part in raw_value.split(","):
        try:
            value = int(raw_part.strip())
        except ValueError:
            continue
        if 1 <= value <= 8:
            indexes.add(value)
    return indexes or {1}


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
