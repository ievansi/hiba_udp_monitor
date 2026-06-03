import logging
import socket
from pathlib import Path
from threading import Thread
from typing import Any

import yaml

from csv_logger import CsvLogger
from data_store import DataStore
from hiba_decoder import (
    CHANNEL_COUNT,
    DEVICE_COUNT,
    ChannelConfig,
    DecodeError,
    DeviceConfig,
    decode_hiba_packet,
)


LOGGER = logging.getLogger(__name__)


class _IndentedYamlDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, indentless=False)


def load_monitor_config(path: str) -> tuple[list[DeviceConfig], list[ChannelConfig]]:
    with Path(path).open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    raw_devices: list[dict[str, Any]] = config.get("devices", [])
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
                name=str(raw_device.get("name", f"MD880_{index}")),
                model=str(raw_device.get("model", "MD880")),
                enabled=bool(raw_device.get("enabled", True)),
            )
        )

    raw_channels: list[dict[str, Any]] = config.get("channels", [])
    if len(raw_channels) != CHANNEL_COUNT:
        raise ValueError(f"config.yaml must define exactly {CHANNEL_COUNT} channels")

    channels: list[ChannelConfig] = []
    for index, raw_channel in enumerate(raw_channels, start=1):
        channels.append(
            ChannelConfig(
                index=index,
                name=str(raw_channel.get("name", f"Channel {index}")),
                tag=str(raw_channel.get("tag", _default_tag(index, raw_channel))),
                parameter=str(raw_channel.get("parameter", "")),
                scale=float(raw_channel.get("scale", 1.0)),
                unit=str(raw_channel.get("unit", "")),
                signed=bool(raw_channel.get("signed", False)),
                warning_low=_optional_float(raw_channel.get("warning_low")),
                warning_high=_optional_float(raw_channel.get("warning_high")),
                alarm_low=_optional_float(raw_channel.get("alarm_low")),
                alarm_high=_optional_float(raw_channel.get("alarm_high")),
            )
        )
    return devices, channels


def load_channel_config(path: str) -> list[ChannelConfig]:
    return load_monitor_config(path)[1]


def save_monitor_config(
    path: str,
    devices: list[DeviceConfig],
    channels: list[ChannelConfig],
) -> None:
    config = {
        "devices": [
            {
                "name": device.name,
                "model": device.model,
                "enabled": device.enabled,
            }
            for device in devices
        ],
        "channels": [
            {
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
            for channel in channels
        ]
    }
    with Path(path).open("w", encoding="utf-8") as file:
        yaml.dump(
            config,
            file,
            Dumper=_IndentedYamlDumper,
            allow_unicode=True,
            sort_keys=False,
        )


def save_channel_config(path: str, channels: list[ChannelConfig]) -> None:
    devices = [
        DeviceConfig(index=index, name=f"MD880_{index}")
        for index in range(1, DEVICE_COUNT + 1)
    ]
    save_monitor_config(path, devices, channels)


def _optional_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _default_tag(index: int, raw_channel: dict[str, Any]) -> str:
    parameter = str(raw_channel.get("parameter", "")).strip()
    if parameter:
        return parameter.replace("-", "_").upper()
    return f"TAG_{index}"


class HibaUdpReceiver:
    def __init__(
        self,
        host: str,
        port: int,
        allowed_source_ip: str,
        devices: list[DeviceConfig],
        channels: list[ChannelConfig],
        store: DataStore,
        logger: CsvLogger,
    ) -> None:
        self.host = host
        self.port = port
        self.allowed_source_ip = allowed_source_ip
        self.devices = devices
        self.channels = channels
        self.store = store
        self.logger = logger
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._thread = Thread(target=self._run, name="hiba-udp-receiver", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            LOGGER.info("Listening for HIBA UDP packets on %s:%s", self.host, self.port)

            while True:
                packet, address = sock.recvfrom(4096)
                source_ip = address[0]

                if self.allowed_source_ip and source_ip != self.allowed_source_ip:
                    self.store.add_ignored_packet(source_ip)
                    continue

                try:
                    decoded = decode_hiba_packet(
                        packet,
                        self.channels,
                        self.devices,
                        source_ip,
                    )
                except DecodeError as exc:
                    self.store.add_decode_error(str(exc), source_ip)
                    LOGGER.warning("Failed to decode UDP packet from %s: %s", source_ip, exc)
                    continue
                except Exception as exc:
                    self.store.add_decode_error(str(exc), source_ip)
                    LOGGER.exception("Unexpected UDP decode error from %s", source_ip)
                    continue

                latest = self.store.add_packet(decoded)
                try:
                    self.logger.log(latest)
                except Exception:
                    LOGGER.exception("Failed to write CSV log row")
