"""Client for the Triad AMS 24x24 audio matrix (bass / treble / balance).

The AMS speaks a small binary-in, text-out protocol over TCP. Frames are
``FF 55 04 03 <command> <F5 for get | output> ...`` followed by the zero-based
output byte (and a value byte for sets). Replies are null-terminated text, for
example ``Get Out[2] Bass : 0`` or ``Set Out[10] Balance to Bal R 1``.

Values are one byte: 0x00..0x30 where 0x18 is 0 dB (or centered), at 0.5 dB
per step, giving -12 dB .. +12 dB.

Each batch of commands uses one short-lived connection so the integration
never holds the amp's TCP connection open (the Control4 controller uses it too).
"""

from __future__ import annotations

import asyncio
import logging
import re

_LOGGER = logging.getLogger(__name__)

# Command bytes (from the Triad AMS driver command list)
CMD_BASS = 0x2F
CMD_TREBLE = 0x30
CMD_BALANCE = 0x31

KIND_BASS = "bass"
KIND_TREBLE = "treble"
KIND_BALANCE = "balance"
KIND_COMMANDS = {KIND_BASS: CMD_BASS, KIND_TREBLE: CMD_TREBLE, KIND_BALANCE: CMD_BALANCE}

VALUE_ZERO = 0x18  # 0 dB / centered
VALUE_MAX = 0x30  # +12 dB / full right
DB_PER_STEP = 0.5

_PREFIX = bytes([0xFF, 0x55, 0x04, 0x03])
_GET_MARKER = 0xF5

_NUMBER_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*$")
_BALANCE_RE = re.compile(r"Bal\s+([LR])\s+(\d+(?:\.\d+)?)", re.IGNORECASE)


class TriadError(Exception):
    """Raised when the AMS cannot be reached or answers unexpectedly."""


def db_to_byte(db: float) -> int:
    """Convert dB (or balance steps in dB, + is right) to the amp's value byte."""
    value = VALUE_ZERO + int(round(db / DB_PER_STEP))
    return max(0, min(VALUE_MAX, value))


def parse_value(kind: str, text: str) -> float | None:
    """Parse a reply such as 'Get Out[2] Bass : -3' into dB (balance: + is right)."""
    if kind == KIND_BALANCE:
        if "center" in text.lower():
            return 0.0
        match = _BALANCE_RE.search(text)
        if match:
            amount = float(match.group(2))
            return amount if match.group(1).upper() == "R" else -amount
        return None
    match = _NUMBER_RE.search(text.split(":", 1)[-1])
    return float(match.group(1)) if match else None


class TriadAms:
    """Talks to one Triad AMS."""

    def __init__(
        self, host: str, port: int, connect_timeout: float, reply_timeout: float
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._reply_timeout = reply_timeout
        self._lock = asyncio.Lock()

    async def _exchange(self, frames: list[bytes]) -> list[str]:
        """Send frames in order on one connection; return one reply per frame."""
        async with self._lock:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=self._connect_timeout,
                )
            except (OSError, TimeoutError) as err:
                raise TriadError(
                    f"cannot connect to {self._host}:{self._port}: {err}"
                ) from err
            replies: list[str] = []
            try:
                for frame in frames:
                    writer.write(frame)
                    await writer.drain()
                    try:
                        raw = await asyncio.wait_for(
                            reader.readuntil(b"\x00"), timeout=self._reply_timeout
                        )
                    except (TimeoutError, asyncio.IncompleteReadError) as err:
                        raise TriadError(f"no reply to {frame.hex(' ')}") from err
                    replies.append(raw.decode("ascii", errors="replace").strip("\x00 \r\n"))
            except OSError as err:
                raise TriadError(f"connection error: {err}") from err
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
            return replies

    @staticmethod
    def _get_frame(kind: str, output: int) -> bytes:
        return _PREFIX + bytes([KIND_COMMANDS[kind], _GET_MARKER, output])

    @staticmethod
    def _set_frame(kind: str, output: int, value: int) -> bytes:
        return _PREFIX + bytes([KIND_COMMANDS[kind], output, value])

    async def async_read_all(self, outputs: list[int]) -> dict[int, dict[str, float | None]]:
        """Read bass, treble and balance for each output on one connection."""
        frames: list[bytes] = []
        order: list[tuple[int, str]] = []
        for output in outputs:
            for kind in (KIND_BASS, KIND_TREBLE, KIND_BALANCE):
                frames.append(self._get_frame(kind, output))
                order.append((output, kind))
        replies = await self._exchange(frames)
        result: dict[int, dict[str, float | None]] = {out: {} for out in outputs}
        for (output, kind), text in zip(order, replies, strict=True):
            value = parse_value(kind, text)
            if value is None:
                _LOGGER.debug("Unparsed Triad reply for out %s %s: %r", output, kind, text)
            result[output][kind] = value
        return result

    async def async_set(self, kind: str, output: int, db: float) -> str:
        """Set one value; returns the amp's acknowledgement text."""
        frame = self._set_frame(kind, output, db_to_byte(db))
        (reply,) = await self._exchange([frame])
        if not reply.lower().startswith("set out"):
            raise TriadError(f"unexpected reply to set {kind} on output {output}: {reply!r}")
        return reply
