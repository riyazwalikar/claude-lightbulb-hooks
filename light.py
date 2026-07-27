"""Wipro/Tuya smart bulb CLI controller. Supports cloud API and local LAN."""

import tinytuya
import json
import os
import sys
import argparse
import colorsys
import time

COLORS = {
    'red': (0, 255, 255),
    'green': (120, 255, 255),
    'yellow': (60, 255, 255),
    'blue': (240, 255, 255),
    'orange': (30, 255, 255),
    'purple': (270, 255, 255),
    'pink': (330, 200, 255),
    'cyan': (180, 255, 255),
    'white': (0, 0, 255),
    'warmwhite': (30, 80, 255),
}


def load_config(path):
    with open(path) as f:
        return json.load(f)


def connect_cloud(cfg):
    for k in ('api_key', 'api_secret', 'api_region', 'device_id'):
        if k not in cfg:
            sys.exit(f'Config key "{k}" required for cloud mode.')
    return tinytuya.Cloud(
        apiRegion=cfg['api_region'],
        apiKey=cfg['api_key'],
        apiSecret=cfg['api_secret'],
        apiDeviceID=cfg['device_id'],
    )


def connect_lan(cfg, ip):
    for k in ('device_id', 'device_local_key'):
        if k not in cfg:
            sys.exit(f'Config key "{k}" required for LAN mode.')
    return tinytuya.BulbDevice(
        dev_id=cfg['device_id'],
        address=ip,
        local_key=cfg['device_local_key'],
        version=cfg.get('device_version', 3.3),
    )


# --- Cloud helpers ---

def cloud_status(c, dev_id):
    s = c.getstatus(dev_id)
    if not s.get('success'):
        sys.exit(f'ERROR: {s}')
    return {p['code']: p['value'] for p in s['result']}


def cloud_send(c, dev_id, code, value):
    r = c.sendcommand(dev_id, {'commands': [{'code': code, 'value': value}]})
    if not r.get('success'):
        sys.exit(f'ERROR: {r}')


def cloud_send_batch(c, dev_id, commands):
    """Send multiple commands in one API call. commands = [(code, value), ...]"""
    r = c.sendcommand(dev_id, {'commands': [{'code': c, 'value': v} for c, v in commands]})
    if not r.get('success'):
        sys.exit(f'ERROR: {r}')


# --- LAN helpers ---

def lan_status(d):
    s = d.status()
    if 'Error' in s:
        sys.exit(f'ERROR: {s}')
    dps = s.get('dps', {})
    return {
        'switch_led': dps.get('1', None),
        'work_mode': dps.get('2', 'white'),
        'bright_value': dps.get('3', 0),
        'colour_data': dps.get('5', '{}'),
    }


def lan_send(d, code, value):
    code_map = {
        'switch_led': '1',
        'work_mode': '2',
        'bright_value': '3',
        'colour_data': '5',
    }
    if code not in code_map:
        sys.exit(f'Unknown LAN code: {code}')
    dps = code_map[code]
    d.set_value(dps, value)


# --- Shared ---

def pct_to_val(pct):
    """0-100% -> device range 25-255."""
    return max(25, int(pct * 2.3 + 25))


def val_to_pct(val):
    """Device range 25-255 -> 0-100%."""
    if isinstance(val, (int, float)):
        return int((val - 25) / 2.3)
    return 0


def parse_color(val):
    """Return HSV tuple (h:0-360, s:0-255, v:0-255)."""
    v = val.lower()
    if v in COLORS:
        return COLORS[v]
    if v.startswith('#'):
        h = v.lstrip('#')
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        hsv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        return (int(hsv[0] * 360), int(hsv[1] * 255), int(hsv[2] * 255))
    sys.exit(f'Unknown color "{val}". Use name or #RRGGBB.')


# --- Main ---

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('-s', '--switch', choices=['on', 'off'])
    ap.add_argument('-b', '--brightness', type=int, help='Brightness percentage (0-100)')
    ap.add_argument('-C', '--color', help='Color name (red, green, ...) or hex (#ff0000)')
    ap.add_argument('-c', '--config', default='light.json', help='Config file path')
    ap.add_argument('--need-attention', action='store_true',
                    help='Pulse red between 10%% and 100%% every second')
    ap.add_argument('-q', '--quiet', action='store_true', help='Suppress all output')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--cloud', action='store_true', default=True, help='Use cloud API (default)')
    mode.add_argument('--lan', metavar='IP', help='Use local LAN with device IP')
    args = ap.parse_args()

    if args.quiet:
        sys.stdout = open(os.devnull, 'w')

    cfg = load_config(args.config)

    if args.lan:
        d = connect_lan(cfg, args.lan)
        status_fn = lambda: lan_status(d)
        send_fn = lambda code, val: lan_send(d, code, val)
        dev_id = cfg['device_id']
        mode_name = f'LAN ({args.lan})'
    else:
        c = connect_cloud(cfg)
        dev_id = cfg['device_id']
        status_fn = lambda: cloud_status(c, dev_id)
        send_fn = lambda code, val: cloud_send(c, dev_id, code, val)
        mode_name = 'cloud'

    # Get current status
    props = status_fn()
    switch_state = props.get('switch_led', False)
    brightness_pct = val_to_pct(props.get('bright_value', 25))
    print(f'[{mode_name}] switch={"on" if switch_state else "off"}, brightness={brightness_pct}%')

    if args.need_attention:
        # Turn on, set red, pulse v=25 (10%) <-> v=255 (100%)
        send_fn('switch_led', True)
        time.sleep(0.3)
        send_fn('work_mode', 'colour')
        time.sleep(0.2)
        send_fn('colour_data', json.dumps({'h': 0.0, 's': 255.0, 'v': 255.0}))
        print('Pulsing red — Ctrl+C to stop')
        low = True
        try:
            while True:
                v = 25.0 if low else 255.0  # ~10% vs 100% brightness via HSV V
                if args.lan:
                    send_fn('work_mode', 'colour')
                    send_fn('colour_data', json.dumps({'h': 0.0, 's': 255.0, 'v': v}))
                else:
                    cloud_send_batch(c, dev_id, [
                        ('work_mode', 'colour'),
                        ('colour_data', json.dumps({'h': 0.0, 's': 255.0, 'v': v})),
                    ])
                low = not low
                time.sleep(1)
        except KeyboardInterrupt:
            print('\nStopped.')
    else:
        if args.switch == 'on':
            send_fn('switch_led', True)
        elif args.switch == 'off':
            send_fn('switch_led', False)

        if args.color:
            if args.color.lower() in ('white', 'warmwhite'):
                # White mode — use bright_value for brightness
                send_fn('work_mode', 'white')
                time.sleep(0.2)
                if args.brightness is not None:
                    send_fn('bright_value', pct_to_val(args.brightness))
                print(f'Color -> {args.color} (white mode)')
            else:
                h, s, v = parse_color(args.color)
                send_fn('work_mode', 'colour')
                time.sleep(0.2)
                send_fn('colour_data', json.dumps({'h': float(h), 's': float(s), 'v': float(v)}))
                print(f'Color -> HSV({h}, {s}, {v})')
        elif args.brightness is not None:
            time.sleep(0.2)
            send_fn('bright_value', pct_to_val(args.brightness))

    print('Done!')
