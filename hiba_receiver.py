import logging
import socket
from pathlib import Path
from threading import Thread
from typing import Any

import yaml

from csv_logger import CsvLogger
from data_store import DataStore
from hiba_decoder import CHANNEL_COUNT, ChannelConfig, DecodeError, decode_hiba_packet


LOGGER = logging.getLogger(__name__)


def load_channel_config(path: str) -> list[ChannelConfig]:
    with Path(path).open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    raw_channels: list[dict[str, Any]] = config.get("channels", [])
    if len(raw_channels) != CHANNEL_COUNT:
        raise ValueError(f"config.yaml must define exactly {CHANNEL_COUNT} channels")

    channels: list[ChannelConfig] = []
    for index, raw_channel in enumerate(raw_channels, start=1):
        channels.append(
            ChannelConfig(
                index=index,
                name=str(raw_channel.get("name", f"Channel {index}")),
                parameter=str(raw_channel.get("parameter", "")),
                scale=float(raw_channel.get("scale", 1.0)),
                unit=str(raw_channel.get("unit", "")),
                signed=bool(raw_channel.get("signed", False)),
            )
        )
    return channels


class HibaUdpReceiver:
    def __init__(
        self,
        host: str,
        port: int,
        allowed_source_ip: str,
        channels: list[ChannelConfig],
        store: DataStore,
        logger: CsvLogger,
    ) -> None:
        self.host = host
        self.port = port
        self.allowed_source_ip = allowed_source_ip
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
                    decoded = decode_hiba_packet(packet, self.channels, source_ip)
                except DecodeError as exc:
                    self.store.add_decode_error(str(exc), source_ip)
                    LOGGER.warning("Failed to decode UDP packet from %s: %s", source_ip, exc)
                    continue
                except Exception as exc:
                    self.store.add_decode_error(str(exc), source_ip)
                    LOGGER.exception("Unexpected UDP decode error from %s", source_ip)
                    continue

                self.store.add_packet(decoded)
                latest = self.store.latest()
                try:
                    self.logger.log(latest)
                except Exception:
                    LOGGER.exception("Failed to write CSV log row")
