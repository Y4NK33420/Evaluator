#!/usr/bin/env python3
"""Length-prefixed guest-agent probe client over Firecracker AF_UNIX vsock proxy."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from typing import Any


def _read_exact(sock: socket.socket, total: int) -> bytes:
    chunks: list[bytes] = []
    remaining = total
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("stream closed before full response frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _send_frame(sock: socket.socket, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    sock.sendall(len(body).to_bytes(4, "big"))
    sock.sendall(body)


def _recv_frame(sock: socket.socket) -> dict[str, Any]:
    header = _read_exact(sock, 4)
    size = int.from_bytes(header, "big")
    if size <= 0 or size > 8 * 1024 * 1024:
        raise RuntimeError(f"invalid frame size: {size}")
    body = _read_exact(sock, size)
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("response payload is not a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uds-path", required=True)
    parser.add_argument("--port", type=int, default=7000)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--payload-file", required=True)
    args = parser.parse_args()

    if not hasattr(socket, "AF_UNIX"):
        print("AF_UNIX is unavailable on this host", file=sys.stderr)
        return 2

    with open(args.payload_file, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(args.timeout)
            sock.connect(args.uds_path)
            sock.sendall(f"CONNECT {args.port}\n".encode("ascii"))

            ack = b""
            while not ack.endswith(b"\n"):
                chunk = sock.recv(1)
                if not chunk:
                    raise RuntimeError("vsock proxy closed connection before ACK")
                ack += chunk
                if len(ack) > 256:
                    raise RuntimeError("vsock proxy ACK is too large")

            ack_text = ack.decode("utf-8", errors="replace").strip()
            if not ack_text.startswith("OK "):
                raise RuntimeError(f"vsock proxy rejected CONNECT request: {ack_text}")

            _send_frame(sock, payload)
            response = _recv_frame(sock)
    except Exception as exc:
        print(f"vsock request failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(response, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
