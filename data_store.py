from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any
from uuid import uuid4


class DataStore:
    def __init__(
        self,
        history_limit: int = 10000,
        active_timeout_seconds: float = 3.0,
        history_sample_interval_seconds: float = 0.2,
    ) -> None:
        self._lock = Lock()
        self._history_limit = history_limit
        self._active_timeout_seconds = active_timeout_seconds
        self._history_sample_interval_seconds = history_sample_interval_seconds
        self._latest: dict[str, Any] | None = None
        self._history: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._packet_count = 0
        self._decode_errors = 0
        self._ignored_packets = 0
        self._last_error: str | None = None
        self._last_source_ip: str | None = None
        self._latest_received_at: float | None = None
        self._last_history_sample_at: float | None = None
        self._annotations: list[dict[str, Any]] = []
        self._events: deque[dict[str, Any]] = deque(maxlen=5000)
        self._alarm_states: dict[tuple[int, int], str] = {}

    def add_packet(self, packet: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            now = monotonic()
            self._packet_count += 1
            packet = deepcopy(packet)
            packet["packet_count"] = self._packet_count
            self._latest = packet
            self._record_alarm_events_locked(packet)
            self._last_error = None
            self._last_source_ip = packet.get("source_ip")
            self._latest_received_at = now
            if self._should_store_history_sample_locked(now):
                self._history.append(packet)
                self._last_history_sample_at = now
            return packet

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
                    "fresh": False,
                    "active_device_count": 0,
                    "max_devices": 16,
                    "devices": [],
                    "channels": [],
                }
            latest = deepcopy(self._latest)
            latest["fresh"] = self._has_fresh_data_locked()
            if not latest["fresh"]:
                latest["active_device_count"] = 0
                for device in latest.get("devices", []):
                    device["quality"] = "OFFLINE"
                    for channel in device.get("channels", []):
                        channel["quality"] = "OFFLINE"
            return latest

    def history(self, limit: int | None = None) -> dict[str, Any]:
        with self._lock:
            items = list(self._history)
            if limit is not None:
                items = items[-limit:]
            return {
                "packet_count": self._packet_count,
                "items": deepcopy(items),
            }

    def history_for_chart(
        self,
        device_index: int,
        channel_indexes: set[int],
        limit: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            items = list(self._history)
            packet_count = self._packet_count

        if limit is not None:
            items = items[-limit:]

        filtered_items = []
        for item in items:
            device = next(
                (
                    candidate
                    for candidate in item.get("devices", [])
                    if candidate.get("index") == device_index
                ),
                None,
            )
            if not device:
                continue

            filtered_items.append(
                {
                    "timestamp": item.get("timestamp"),
                    "packet_count": item.get("packet_count"),
                    "source_ip": item.get("source_ip"),
                    "device_index": device_index,
                    "device_active": device.get("active", False),
                    "channels": [
                        {
                            "index": channel.get("index"),
                            "value": channel.get("value"),
                            "unit": channel.get("unit"),
                            "tag": channel.get("tag"),
                            "parameter": channel.get("parameter"),
                            "quality": channel.get("quality"),
                            "alarm_state": channel.get("alarm_state"),
                        }
                        for channel in device.get("channels", [])
                        if channel.get("index") in channel_indexes
                    ],
                }
            )

        return {
            "packet_count": packet_count,
            "device_index": device_index,
            "channel_indexes": sorted(channel_indexes),
            "items": filtered_items,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            has_fresh_data = self._has_fresh_data_locked()
            active_device_count = 0
            max_devices = 16
            if has_fresh_data and self._latest:
                active_device_count = int(self._latest.get("active_device_count", 0))
                max_devices = int(self._latest.get("max_devices", max_devices))
            return {
                "packet_count": self._packet_count,
                "decode_errors": self._decode_errors,
                "ignored_packets": self._ignored_packets,
                "last_error": self._last_error,
                "last_source_ip": self._last_source_ip,
                "has_data": self._latest is not None,
                "has_live_data": has_fresh_data,
                "active_device_count": active_device_count,
                "max_devices": max_devices,
                "active_timeout_seconds": self._active_timeout_seconds,
                "history_limit": self._history_limit,
                "history_sample_interval_seconds": self._history_sample_interval_seconds,
            }

    def add_annotation(self, annotation: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            stored = deepcopy(annotation)
            stored["id"] = str(uuid4())
            self._annotations.append(stored)
            return deepcopy(stored)

    def annotations(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._annotations)

    def events(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self._events)[-limit:])

    def _has_fresh_data_locked(self) -> bool:
        if self._latest_received_at is None:
            return False
        return monotonic() - self._latest_received_at <= self._active_timeout_seconds

    def _should_store_history_sample_locked(self, now: float) -> bool:
        if self._last_history_sample_at is None:
            return True
        return now - self._last_history_sample_at >= self._history_sample_interval_seconds

    def _record_alarm_events_locked(self, packet: dict[str, Any]) -> None:
        timestamp = packet.get("timestamp") or datetime.now(timezone.utc).isoformat()
        for device in packet.get("devices", []):
            device_index = int(device.get("index", 0))
            device_name = str(device.get("name", f"Device {device_index}"))
            if not device.get("active"):
                continue
            for channel in device.get("channels", []):
                channel_index = int(channel.get("index", 0))
                key = (device_index, channel_index)
                state = str(channel.get("alarm_state", "normal"))
                previous_state = self._alarm_states.get(key, "normal")
                if state == previous_state:
                    continue

                self._alarm_states[key] = state
                if state == "normal":
                    event_type = "alarm_cleared"
                    severity = "info"
                    message = "Alarm cleared"
                elif state.startswith("warning"):
                    event_type = "threshold_warning"
                    severity = "warning"
                    message = f"Warning threshold reached: {state}"
                elif state.startswith("alarm"):
                    event_type = "threshold_alarm"
                    severity = "alarm"
                    message = f"Alarm threshold reached: {state}"
                else:
                    continue

                self._events.append(
                    {
                        "id": str(uuid4()),
                        "timestamp": timestamp,
                        "type": event_type,
                        "severity": severity,
                        "message": message,
                        "device_index": device_index,
                        "device_name": device_name,
                        "channel_index": channel_index,
                        "channel_name": channel.get("name"),
                        "tag": channel.get("tag"),
                        "parameter": channel.get("parameter"),
                        "value": channel.get("value"),
                        "unit": channel.get("unit"),
                        "state": state,
                        "previous_state": previous_state,
                    }
                )
