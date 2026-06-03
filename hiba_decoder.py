from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


CHANNEL_COUNT = 8
DEVICE_COUNT = 16
PAYLOAD_START_OFFSET = 12
CHANNEL_WIDTH = 2
DEVICE_SLOT_WIDTH = CHANNEL_COUNT * CHANNEL_WIDTH
EXPECTED_PACKET_LENGTH = 270
TRAILER_WIDTH = 2
MIN_PACKET_LENGTH = EXPECTED_PACKET_LENGTH


@dataclass(frozen=True)
class ChannelConfig:
    index: int
    name: str
    tag: str
    parameter: str
    scale: float
    unit: str
    signed: bool = False
    warning_low: float | None = None
    warning_high: float | None = None
    alarm_low: float | None = None
    alarm_high: float | None = None


@dataclass(frozen=True)
class DeviceConfig:
    index: int
    name: str
    model: str = "MD880"
    enabled: bool = True


class DecodeError(ValueError):
    pass


def decode_hiba_packet(
    packet: bytes,
    channels: list[ChannelConfig],
    devices: list[DeviceConfig],
    source_ip: str,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    if len(packet) < MIN_PACKET_LENGTH:
        raise DecodeError(
            f"Packet is too short: got {len(packet)} bytes, need at least {MIN_PACKET_LENGTH}"
        )

    timestamp = timestamp or datetime.now(timezone.utc)
    decoded_devices = []

    for device_index in range(1, DEVICE_COUNT + 1):
        base_offset = PAYLOAD_START_OFFSET + (device_index - 1) * DEVICE_SLOT_WIDTH
        device_config = _device_config_for_index(devices, device_index)
        decoded_channels = []
        device_has_data = False

        for channel in channels:
            offset = base_offset + (channel.index - 1) * CHANNEL_WIDTH
            raw_bytes = packet[offset : offset + CHANNEL_WIDTH]
            raw_unsigned = int.from_bytes(raw_bytes, "little", signed=False)
            raw = int.from_bytes(raw_bytes, "little", signed=channel.signed)
            value = raw * channel.scale
            if raw_unsigned != 0:
                device_has_data = True
            alarm_state = _alarm_state(value, channel)
            decoded_channels.append(
                {
                    "index": channel.index,
                    "name": channel.name,
                    "tag": channel.tag,
                    "parameter": channel.parameter,
                    "raw": raw,
                    "raw_unsigned": raw_unsigned,
                    "value": value,
                    "unit": channel.unit,
                    "offset": offset,
                    "signed": channel.signed,
                    "data_type": "int16" if channel.signed else "uint16",
                    "quality": "GOOD",
                    "alarm_state": alarm_state,
                    "alarm_limits": {
                        "warning_low": channel.warning_low,
                        "warning_high": channel.warning_high,
                        "alarm_low": channel.alarm_low,
                        "alarm_high": channel.alarm_high,
                    },
                    "active": False,
                }
            )

        device_active = device_has_data and device_config.enabled
        for decoded_channel in decoded_channels:
            decoded_channel["active"] = device_active
            if not device_has_data or not device_config.enabled:
                decoded_channel["quality"] = "INACTIVE_SLOT"
                decoded_channel["alarm_state"] = "inactive"

        decoded_devices.append(
            {
                "index": device_index,
                "name": device_config.name,
                "model": device_config.model,
                "enabled": device_config.enabled,
                "base_offset": base_offset,
                "active": device_active,
                "quality": "GOOD" if device_active else "INACTIVE_SLOT",
                "channels": decoded_channels,
            }
        )

    active_device_count = sum(1 for device in decoded_devices if device["active"])

    return {
        "timestamp": timestamp.isoformat(),
        "source_ip": source_ip,
        "packet_length": len(packet),
        "expected_packet_length": EXPECTED_PACKET_LENGTH,
        "max_devices": DEVICE_COUNT,
        "active_device_count": active_device_count,
        "header": {
            "hex": packet[:PAYLOAD_START_OFFSET].hex(" "),
            "start_marker": packet[:2].hex(" "),
            "payload_length_be": int.from_bytes(packet[4:6], "big", signed=False)
            if len(packet) >= 6
            else None,
            "trailer": packet[-TRAILER_WIDTH:].hex(" ")
            if len(packet) >= TRAILER_WIDTH
            else "",
        },
        "validation": {
            "start_marker_ok": packet[:2] == b"\xa5\xa5",
            "trailer_ok": packet[-TRAILER_WIDTH:] == b"\x5a\x5a",
            "length_ok": len(packet) == EXPECTED_PACKET_LENGTH,
            "payload_length_field_ok": int.from_bytes(packet[4:6], "big", signed=False)
            == len(packet)
            if len(packet) >= 6
            else False,
        },
        "raw_packet_hex": packet.hex(" "),
        "devices": decoded_devices,
        "channels": decoded_devices[0]["channels"],
    }


def _device_config_for_index(devices: list[DeviceConfig], index: int) -> DeviceConfig:
    for device in devices:
        if device.index == index:
            return device
    return DeviceConfig(index=index, name=f"MD880_{index}")


def _alarm_state(value: float, channel: ChannelConfig) -> str:
    if channel.alarm_low is not None and value < channel.alarm_low:
        return "alarm_low"
    if channel.alarm_high is not None and value > channel.alarm_high:
        return "alarm_high"
    if channel.warning_low is not None and value < channel.warning_low:
        return "warning_low"
    if channel.warning_high is not None and value > channel.warning_high:
        return "warning_high"
    return "normal"
