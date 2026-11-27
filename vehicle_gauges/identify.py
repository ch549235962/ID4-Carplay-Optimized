"""Bounded, identification-only HSFZ reader; no arbitrary diagnostic commands."""
from __future__ import annotations
import ipaddress
import re
import socket
import struct
import time

IDENTIFIERS = {'vin': 0xF190, 'part_number': 0xF187,
               'software_number': 0xF188, 'software_version': 0xF189}


class IdentificationError(ValueError):
    pass


class IdentificationReader:
    def __init__(self, host, ecu=0x12, timeout=3.0, connect=socket.create_connection):
        self.host = str(ipaddress.IPv4Address(host))
        if type(ecu) is not int or not 1 <= ecu <= 0xEF:
            raise IdentificationError('ECU address must be between 01 and EF')
        if not 0.1 <= timeout <= 10:
            raise IdentificationError('Invalid timeout')
        self.ecu, self.timeout, self.connect = ecu, timeout, connect

    def read(self, name):
        # No public arbitrary-SID API: even callers can only request these IDs.
        if name not in IDENTIFIERS:
            raise IdentificationError('Only identification DIDs are permitted')
        did = IDENTIFIERS[name].to_bytes(2, 'big')
        request = b'\x22' + did
        body = bytes([0xF4, self.ecu]) + request
        deadline = time.monotonic() + self.timeout
        with self.connect((self.host, 6801), timeout=self.timeout) as sock:
            sock.sendall(struct.pack('>IH', len(body), 1) + body)

            def exact(count):
                value = bytearray()
                while len(value) < count:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise TimeoutError('ECU identification timed out')
                    sock.settimeout(left)
                    part = sock.recv(count-len(value))
                    if not part:
                        raise IdentificationError('Truncated HSFZ response')
                    value.extend(part)
                return bytes(value)

            for _ in range(32):
                length, control = struct.unpack('>IH', exact(6))
                if not 2 <= length <= 4096:
                    raise IdentificationError('Invalid HSFZ length')
                reply = exact(length)
                if control == 2:  # HSFZ acknowledgement is not ECU data.
                    continue
                if control != 1 or reply[:2] != bytes([self.ecu, 0xF4]):
                    continue
                uds = reply[2:]
                if uds[:2] == b'\x7f\x22':
                    if len(uds) != 3:
                        raise IdentificationError('Malformed negative response')
                    if uds[2] == 0x78:
                        continue  # Pending never extends the overall deadline.
                    raise IdentificationError(f'Identification unsupported: NRC {uds[2]:02X}')
                if uds[:3] != b'\x62' + did:
                    continue
                raw = uds[3:]
                if not raw or len(raw) > 256:
                    raise IdentificationError('Invalid identification payload')
                return raw
        raise IdentificationError('No matching identification response')

    def collect(self):
        result = {'schema': 1, 'ecu_address': self.ecu, 'identifiers': {}, 'errors': {}}
        for name in IDENTIFIERS:
            try:
                raw = self.read(name)
                result['identifiers'][name] = raw.hex()
            except (OSError, IdentificationError) as error:
                # Never put a socket's address or raw command into the report.
                result['errors'][name] = str(error) if isinstance(error, IdentificationError) else type(error).__name__
        return result


def vin_from_report(report):
    try:
        value = bytes.fromhex(report['identifiers']['vin']).decode('ascii').strip('\x00 ')
    except (KeyError, ValueError, UnicodeError, TypeError):
        raise IdentificationError('ECU did not supply a valid VIN') from None
    if not re.fullmatch('[A-HJ-NPR-Z0-9]{17}', value):
        raise IdentificationError('ECU did not supply a valid VIN')
    return value
