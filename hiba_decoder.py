from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


CHANNEL_COUNT = 8
CHANNEL_START_OFFSET = 12
CHANNEL_WIDTH = 2
MIN_PACKET_LENGTH = CHANNEL_START_OFFSET + CHANNEL_COUNT * CHANNEL_WIDTH
EXPECTED_PACKET_LENGTH = 270


@dataclass(frozen=True)
class ChannelConfig:
    index: int
    name: str
    parameter: str
    scale: float
    unit: str
    signed: bool = False


class DecodeError(ValueError):
    pass


def decode_hiba_packet(
    packet: bytes,
    channels: list[ChannelConfig],
    source_ip: str,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    if len(packet) < MIN_PACKET_LENGTH:
        raise DecodeError(
            f"Packet is too short: got {len(packet)} bytes, need at least {MIN_PACKET_LENGTH}"
        )

    timestamp = timestamp or datetime.now(timezone.utc)
    decoded_channels = []

    for channel in channels:
        offset = CHANNEL_START_OFFSET + (channel.index - 1) * CHANNEL_WIDTH
        raw = int.from_bytes(
            packet[offset : offset + CHANNEL_WIDTH],
            "little",
            signed=channel.signed,
        )
        decoded_channels.append(
            {
                "index": channel.index,
                "name": channel.name,
                "parameter": channel.parameter,
                "raw": raw,
                "value": raw * channel.scale,
                "unit": channel.unit,
                "offset": offset,
                "signed": channel.signed,
                "data_type": "int16" if channel.signed else "uint16",
            }
        )

    return {
        "timestamp": timestamp.isoformat(),
        "source_ip": source_ip,
        "packet_length": len(packet),
        "expected_packet_length": EXPECTED_PACKET_LENGTH,
        "channels": decoded_channels,
    }
