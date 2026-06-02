from collections import deque
from copy import deepcopy
from threading import Lock
from typing import Any


class DataStore:
    def __init__(self, history_limit: int = 1000) -> None:
        self._lock = Lock()
        self._latest: dict[str, Any] | None = None
        self._history: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._packet_count = 0
        self._decode_errors = 0
        self._ignored_packets = 0
        self._last_error: str | None = None
        self._last_source_ip: str | None = None

    def add_packet(self, packet: dict[str, Any]) -> None:
        with self._lock:
            self._packet_count += 1
            packet = deepcopy(packet)
            packet["packet_count"] = self._packet_count
            self._latest = packet
            self._history.append(packet)
            self._last_error = None
            self._last_source_ip = packet.get("source_ip")

    def add_decode_error(self, message: str, source_ip: str | None = None) -> None:
        with self._lock:
            self._decode_errors += 1
            self._last_error = message
            if source_ip:
                self._last_source_ip = source_ip

    def add_ignored_packet(self, source_ip: str) -> None:
        with self._lock:
            self._ignored_packets += 1
            self._last_source_ip = source_ip

    def latest(self) -> dict[str, Any]:
        with self._lock:
            if self._latest is None:
                return {
                    "packet_count": self._packet_count,
                    "source_ip": self._last_source_ip,
                    "timestamp": None,
                    "channels": [],
                }
            return deepcopy(self._latest)

    def history(self) -> dict[str, Any]:
        with self._lock:
            return {
                "packet_count": self._packet_count,
                "items": deepcopy(list(self._history)),
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "packet_count": self._packet_count,
                "decode_errors": self._decode_errors,
                "ignored_packets": self._ignored_packets,
                "last_error": self._last_error,
                "last_source_ip": self._last_source_ip,
                "has_data": self._latest is not None,
            }
