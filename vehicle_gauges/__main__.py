"""python -m vehicle_gauges identify/plan. No vehicle write or deployment path."""
import argparse
import json
from pathlib import Path
from .identify import IdentificationReader
from .provision import plan
from vehicle_installer.remote import private_json


def main():
    parser = argparse.ArgumentParser(description='NBT 仪表电脑端识别与配置准备（开发版）')
    sub = parser.add_subparsers(dest='action', required=True)
    identify = sub.add_parser('identify', help='仅通过 ENET 读取 ECU 身份，不写车辆')
    identify.add_argument('--gateway', required=True)
    identify.add_argument('--ecu', type=lambda s: int(s, 16), default=0x12)
    identify.add_argument('--output', type=Path, required=True)
    offline = sub.add_parser('plan', help='在电脑上匹配已有身份报告')
    offline.add_argument('--report', type=Path, required=True)
    offline.add_argument('--vin', default='')
    offline.add_argument('--vehicle', default='2014 F20 N13')
    offline.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'identify':
        value = IdentificationReader(args.gateway, args.ecu).collect()
    else:
        if args.report.stat().st_size > 65536:
            parser.error('报告过大')
        value = plan(json.loads(args.report.read_text('utf-8')), args.vin, args.vehicle)
    private_json(args.output, value)
    print('已保存；原始身份报告含 VIN，请保留在本机。' if args.action == 'identify' else
          '匹配状态：' + value['status'] + '；可部署：' + str(value['deployable']))


if __name__ == '__main__':
    main()
