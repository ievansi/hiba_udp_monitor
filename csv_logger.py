import csv
from pathlib import Path
from threading import Lock
from typing import Any

from hiba_decoder import ChannelConfig


class CsvLogger:
    def __init__(self, path: str, channels: list[ChannelConfig]) -> None:
        self.path = Path(path)
        self.channels = channels
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def _ensure_header(self) -> None:
        if self.path.exists() and self.path.stat().st_size > 0:
            return

        header = ["timestamp", "source_ip", "packet_count", "packet_length"]
        for channel in self.channels:
            prefix = f"ch{channel.index}"
            header.extend(
                [
                    f"{prefix}_data_type",
                    f"{prefix}_raw",
                    f"{prefix}_value",
                    f"{prefix}_unit",
                    f"{prefix}_parameter",
                    f"{prefix}_name",
                ]
            )

        with self.path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(header)

    def log(self, packet: dict[str, Any]) -> None:
        with self._lock:
            row = [
                packet.get("timestamp"),
                packet.get("source_ip"),
                packet.get("packet_count"),
                packet.get("packet_length"),
            ]

            channels_by_index = {
                channel["index"]: channel for channel in packet.get("channels", [])
            }
            for channel_config in self.channels:
                channel = channels_by_index.get(channel_config.index, {})
                row.extend(
                    [
                        channel.get("data_type"),
                        channel.get("raw"),
                        channel.get("value"),
                        channel.get("unit"),
                        channel.get("parameter"),
                        channel.get("name"),
                    ]
                )

            with self.path.open("a", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(row)
