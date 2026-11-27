"""No car is contacted: fragmented TCP gateway fixture and synthetic identities."""
import copy
import json
import socket
import struct
import threading
import unittest
from unittest.mock import patch
from .identify import IdentificationReader, IdentificationError, vin_from_report
from . import provision

VIN = 'WBA12345678901234'  # synthetic test string, not a captured vehicle


def report():
    return {'schema': 1, 'ecu_address': 0x12, 'identifiers': {
        'vin': VIN.encode().hex(), 'part_number': b'TEST-PART'.hex(),
        'software_number': b'TEST-SW'.hex(), 'software_version': b'TEST-1'.hex()}}


def frame(control, body):
    return struct.pack('>IH', len(body), control) + body


class ProvisionTests(unittest.TestCase):
    def test_unknown_n13_never_becomes_a_live_profile_from_vin(self):
        value = provision.plan(report())
        self.assertFalse(value['deployable'])
        self.assertFalse(value['vehicle_hint_verified'])
        self.assertEqual(value['status'], 'needs_vehicle_validation')
        self.assertNotIn(VIN, json.dumps(value))
        self.assertEqual(set(value['signals'].values()), {'not_validated'})

    def test_wrong_vin_missing_identity_and_ecu_address_refused(self):
        with self.assertRaises(IdentificationError): provision.plan(report(), 'WBA00000000000000')
        for field in ('vin', 'part_number', 'software_number', 'software_version'):
            value = report(); del value['identifiers'][field]
            with self.subTest(field=field), self.assertRaises(IdentificationError): provision.plan(value)
        value = report(); value['ecu_address'] = 255
        with self.assertRaises(IdentificationError): provision.plan(value)

    def test_modified_plan_does_not_authorize_deployment(self):
        value = provision.plan(report()); value.update(deployable=True, status='matched', profile_id='N13')
        with self.assertRaises(IdentificationError): provision.compile_runtime(value)

    def test_malformed_report_is_not_an_identity(self):
        for value in (None, [], {}, {'schema': 1, 'identifiers': []}):
            with self.subTest(value=value), self.assertRaises(IdentificationError): provision.plan(value)

    def test_exact_ecu_match_and_ambiguous_match(self):
        p = {'id': 'synthetic-only', 'ecu_identity': provision.identity_key(report()),
             'ecu_address': 0x12, 'signals': {}}
        with patch.object(provision, 'VERIFIED_PROFILES', (p,)):
            value = provision.plan(report()); self.assertTrue(value['deployable'])
            value['runtime_policy']['temperature_interval_ms'] = 0
            self.assertEqual(json.loads(provision.compile_runtime(value))['runtime_policy']['temperature_interval_ms'], 1000)
            changed = report(); changed['identifiers']['software_version'] = b'TEST-2'.hex()
            self.assertFalse(provision.plan(changed)['deployable'])
        with patch.object(provision, 'VERIFIED_PROFILES', (p, copy.deepcopy(p))):
            with self.assertRaises(IdentificationError): provision.plan(report())


class TransportTests(unittest.TestCase):
    def exchange(self, response):
        server = socket.socket(); server.bind(('127.0.0.1', 0)); server.listen(1)
        address = server.getsockname(); sent = []
        def serve():
            try:
                with server.accept()[0] as client:
                    data = bytearray()
                    while len(data) < 11:
                        chunk = client.recv(11-len(data))
                        if not chunk: break
                        data.extend(chunk)
                    sent.append(bytes(data))
                    for byte in response: client.sendall(bytes([byte]))
            except (BrokenPipeError, ConnectionResetError): pass
            finally: server.close()
        thread = threading.Thread(target=serve); thread.start()
        reader = IdentificationReader('127.0.0.1', connect=lambda _, timeout: socket.create_connection(address, timeout))
        try: return reader.read('vin'), sent
        finally: thread.join(4); self.assertFalse(thread.is_alive())

    def test_fragmented_ack_wrong_ecu_and_did_are_not_vin(self):
        response = frame(2, b'\xf4\x12')
        response += frame(1, b'\x13\xf4\x62\xf1\x90wrong')
        response += frame(1, b'\x12\xf4\x62\xf1\x87wrong')
        response += frame(1, b'\x12\xf4\x7f\x22\x78')
        response += frame(1, b'\x12\xf4\x62\xf1\x90' + VIN.encode())
        raw, sent = self.exchange(response)
        self.assertEqual(raw, VIN.encode())
        self.assertEqual(sent, [bytes.fromhex('000000050001f41222f190')])

    def test_negative_malformed_and_truncated_responses(self):
        for response in [frame(1, b'\x12\xf4\x7f\x22\x31'), struct.pack('>IH', 5000, 1), b'\x00\x00']:
            with self.subTest(response=response), self.assertRaises(IdentificationError): self.exchange(response)

    def test_reader_cannot_send_live_or_write_requests(self):
        reader = IdentificationReader('127.0.0.1', connect=lambda *_: self.fail('Unexpected network access'))
        for name in ('reset', 'coolant', 'F405', '2E'):
            with self.assertRaises(IdentificationError): reader.read(name)
        with self.assertRaises(IdentificationError): vin_from_report({'identifiers': {'vin': b'not-a-vin'.hex()}})


if __name__ == '__main__': unittest.main()
