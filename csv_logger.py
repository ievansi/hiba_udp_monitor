import csv
import io
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any

from hiba_decoder import ChannelConfig


MAX_LOG_BYTES = 5 * 1024


class CsvLogger:
    def __init__(
        self,
        path: str,
        channels: list[ChannelConfig],
        max_bytes: int = MAX_LOG_BYTES,
        sample_interval_seconds: float = 1.0,
    ) -> None:
        self.path = Path(path)
        self.channels = channels
        self.max_bytes = max_bytes
        self.sample_interval_seconds = sample_interval_seconds
        self._last_write_at: float | None = None
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_header()

    def _build_header(self) -> list[str]:
        return [
            "timestamp",
            "source_ip",
            "packet_count",
            "packet_length",
            "active_device_count",
            "device_index",
            "device_name",
            "device_model",
            "channel_index",
            "channel_name",
            "tag",
            "parameter",
            "data_type",
            "raw",
            "value",
            "unit",
            "quality",
            "alarm_state",
        ]

    def _ensure_header(self) -> None:
        if self.path.exists() and self.path.stat().st_size > 0:
            with self.path.open("r", newline="", encoding="utf-8") as file:
                existing_header = next(csv.reader(file), [])
            expected_header = self._build_header()
            if existing_header == expected_header and self.path.stat().st_size <= self.max_bytes:
                return

        self._rewrite_file([])

    def log(self, packet: dict[str, Any]) -> None:
        with self._lock:
            now = monotonic()
            if not self._should_write_locked(now):
                return

            rows = self._packet_rows(packet)
            self._ensure_header()
            rows_text = self._rows_to_text(rows)
            if self.path.stat().st_size + len(rows_text.encode("utf-8")) > self.max_bytes:
                rows = self._fit_rows(rows)
                self._rewrite_file(rows)
                self._last_write_at = now
                return

            with self.path.open("a", newline="", encoding="utf-8") as file:
                file.write(rows_text)
            self._last_write_at = now

    def _packet_rows(self, packet: dict[str, Any]) -> list[list[Any]]:
        rows = []
        base_row = [
            packet.get("timestamp"),
            packet.get("source_ip"),
            packet.get("packet_count"),
            packet.get("packet_length"),
            packet.get("active_device_count"),
        ]
        for device in packet.get("devices", []):
            if not device.get("active"):
                continue
            for channel in device.get("channels", []):
                rows.append(
                    base_row
                    + [
                        device.get("index"),
                        device.get("name"),
                        device.get("model"),
                        channel.get("index"),
                        channel.get("name"),
                        channel.get("tag"),
                        channel.get("parameter"),
                        channel.get("data_type"),
                        channel.get("raw"),
                        channel.get("value"),
                        channel.get("unit"),
                        channel.get("quality"),
                        channel.get("alarm_state"),
                    ]
                )

        if rows:
            return rows

        return [
            base_row
            + [
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "NO_ACTIVE_DEVICE",
                "",
            ]
        ]

    def _fit_rows(self, rows: list[list[Any]]) -> list[list[Any]]:
        fitted_rows = list(rows)
        while fitted_rows and self._header_and_rows_size(fitted_rows) > self.max_bytes:
            fitted_rows.pop(0)
        return fitted_rows

    def _header_and_rows_size(self, rows: list[list[Any]]) -> int:
        return len((self._rows_to_text([self._build_header()]) + self._rows_to_text(rows)).encode("utf-8"))

    def _rewrite_file(self, rows: list[list[Any]]) -> None:
        fitted_rows = self._fit_rows(rows)
        with self.path.open("w", newline="", encoding="utf-8") as file:
            file.write(self._rows_to_text([self._build_header()]))
            file.write(self._rows_to_text(fitted_rows))

    def _should_write_locked(self, now: float) -> bool:
        if self._last_write_at is None:
            return True
        return now - self._last_write_at >= self.sample_interval_seconds

    @staticmethod
    def _rows_to_text(rows: list[list[Any]]) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerows(rows)
        return buffer.getvalue()
