"""Match exact ECU identification on the computer, never on the head unit.

The production registry intentionally starts empty. Candidate definitions and
standard formulas are not promoted to car-validated profiles automatically.
"""
from __future__ import annotations
import hashlib
import json
import re
from .identify import IdentificationError, vin_from_report

VERIFIED_PROFILES = ()
SIGNALS = ('coolant_temperature', 'oil_temperature', 'boost_pressure')
RUNTIME_POLICY = {'poll_only_when_visible': True, 'stop_on_ecu_mismatch': True,
                  'temperature_interval_ms': 1000, 'pressure_interval_ms': 250,
                  'stale_values': 'show_unavailable', 'max_inflight_requests': 1}


def identity_key(report):
    identifiers = report.get('identifiers', {})
    if not isinstance(identifiers, dict):
        raise IdentificationError('Invalid ECU identification report')
    for name in ('part_number', 'software_number', 'software_version'):
        raw = identifiers.get(name)
        if not isinstance(raw, str) or not 2 <= len(raw) <= 512 or len(raw) % 2:
            raise IdentificationError('Incomplete ECU identity; automatic matching is unavailable')
        try:
            bytes.fromhex(raw)
        except ValueError:
            raise IdentificationError('Invalid ECU identification encoding') from None
    return {name: identifiers[name].lower() for name in
            ('part_number', 'software_number', 'software_version')}


def plan(report, expected_vin='', vehicle_hint='2014 F20 N13'):
    if not isinstance(report, dict) or report.get('schema') != 1 or not isinstance(report.get('identifiers'), dict):
        raise IdentificationError('Unsupported identification report format')
    if not isinstance(vehicle_hint, str) or len(vehicle_hint)>120:
        raise IdentificationError('Invalid vehicle hint')
    vin = vin_from_report(report)
    if expected_vin and vin != expected_vin.strip().upper():
        raise IdentificationError('Entered VIN does not match the ECU VIN; stopped')
    if type(report.get('ecu_address')) is not int or not 1 <= report['ecu_address'] <= 0xEF:
        raise IdentificationError('Invalid ECU address')
    identity = identity_key(report)
    # This is only a stable local binding, not an anonymization guarantee or
    # proof that a particular engine is installed. No online VIN decoder runs.
    binding = hashlib.sha256(('NBT-GAUGES-V1:' + vin).encode()).hexdigest()
    matches = [p for p in VERIFIED_PROFILES
               if p['ecu_identity'] == identity and p['ecu_address'] == report['ecu_address']]
    if len(matches) > 1:
        raise IdentificationError('Ambiguous ECU profiles; automatic matching refused')
    return {'schema': 1, 'vehicle_hint': vehicle_hint, 'vehicle_hint_verified': False,
            'vin_binding_sha256': binding, 'ecu_identity': identity,
            'ecu_address': report['ecu_address'],
            'status': 'matched' if matches else 'needs_vehicle_validation',
            'deployable': bool(matches), 'profile_id': matches[0]['id'] if matches else None,
            'signals': {s: 'not_validated' for s in SIGNALS} if not matches else matches[0]['signals'],
            'runtime_policy': dict(RUNTIME_POLICY),
            'runtime_database_included': False}


def compile_runtime(plan_value):
    # An imported/edited plan is not authority to mark a profile as supported.
    matches = [p for p in VERIFIED_PROFILES if p['id'] == plan_value.get('profile_id')
               and p['ecu_identity'] == plan_value.get('ecu_identity')
               and p['ecu_address'] == plan_value.get('ecu_address')]
    if len(matches) != 1 or plan_value.get('status') != 'matched':
        raise IdentificationError('No car-validated profile; refusing to generate deployable data')
    if not re.fullmatch('[0-9a-f]{64}', plan_value.get('vin_binding_sha256', '')):
        raise IdentificationError('Invalid VIN binding')
    p = matches[0]
    return json.dumps({'schema': 1, 'profile_id': p['id'], 'ecu_identity': p['ecu_identity'],
                       'ecu_address': p['ecu_address'], 'signals': p['signals'],
                       'vin_binding_sha256': plan_value['vin_binding_sha256'],
                       'runtime_policy': RUNTIME_POLICY}, separators=(',', ':'),
                      ensure_ascii=False).encode()
