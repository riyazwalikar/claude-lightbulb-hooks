# Claude Code Lightbulb Hooks

A Wipro/Tuya smart bulb wired into [Claude Code](https://claude.com/claude-code) hooks as an ambient status indicator. The bulb's color tells you what your session is doing without looking at the terminal — idle, working, or waiting on you for a permission decision.

Bulb used: [Wipro NS9400 (Amazon.in)](https://www.amazon.in/wipro-NS9400-Compatible-Assistant-Standard/dp/B095SWYF6M/).

`light.py` is the CLI that drives the bulb (cloud or local LAN). `light-hook.sh` is the wrapper Claude Code's hooks call into.

## Status colors

| Color | Hook event | Meaning |
|---|---|---|
| White | `SessionStart` | Session booted |
| Green | `UserPromptSubmit` | Claude working on your prompt |
| Green | `PreToolUse` | Claude actively running tools — keeps the light fresh during long turns |
| Red | `Notification` (non-idle), `PermissionRequest` | Needs your attention — permission prompt or notification up |
| White | `Notification` (idle ping) | "Waiting for your input" — session idle |
| White | `Stop` | Claude idle, waiting for next prompt |
| White | `SessionEnd` | Session terminated (`/clear`, `/exit`, logout, etc.) |

`Notification` fires for both "permission needed" and the idle "waiting for your input" ping. `light-hook.sh notify` reads the payload and picks white for the idle ping, red otherwise — so red always means *act now*.

## Claude Code hook wiring

Configured in `~/.claude/settings.json`. Each event calls `light-hook.sh <color>`, which reads the hook's stdin JSON and skips the call if `agent_id` is present — meaning it's a subagent, not the main session. Without that guard, every background subagent spawn/exit would re-fire `SessionStart`/`SessionEnd` and stomp the light with the wrong color.

```json
"hooks": {
  "SessionStart": [{ "hooks": [
    { "type": "command", "command": "\"~/.claude/hooks/light-hook.sh\" white" }
  ]}],
  "UserPromptSubmit": [{ "hooks": [
    { "type": "command", "command": "\"~/.claude/hooks/light-hook.sh\" green" }
  ]}],
  "PreToolUse": [{ "hooks": [
    { "type": "command", "command": "\"~/.claude/hooks/light-hook.sh\" green" }
  ]}],
  "Notification": [{ "hooks": [
    { "type": "command", "command": "\"~/.claude/hooks/light-hook.sh\" notify" }
  ]}],
  "PermissionRequest": [{ "hooks": [
    { "type": "command", "command": "\"~/.claude/hooks/light-hook.sh\" red" }
  ]}],
  "Stop": [{ "hooks": [
    { "type": "command", "command": "\"~/.claude/hooks/light-hook.sh\" white" }
  ]}],
  "SessionEnd": [{ "hooks": [
    { "type": "command", "command": "\"~/.claude/hooks/light-hook.sh\" white" }
  ]}]
}
```

### Why `PreToolUse` is needed

Without it, the light goes stale during long turns. `UserPromptSubmit` fires once when you hit enter; the next color event is `Stop` when the turn ends. Between those, a mid-turn `Notification` or `PermissionRequest` paints the bulb red — and it *stays* red even after you approve and Claude resumes working, because nothing resets it. `PreToolUse` fires before every tool call, so the moment work resumes the bulb goes green again. Red then means what it should: Claude is *currently* blocked on you.

### Real example (from a live `~/.claude/settings.json`)

This is the actual `hooks` block from a working setup, paths swapped for placeholders. Note some events run other, unrelated hooks (a mode-tracking plugin, an `rtk` wrapper) alongside the light call — hooks for the same event just run as a list, in order:

```json
"hooks": {
  "SessionStart": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "\"<path-to-node>\" \"~/.claude/hooks/some-other-hook.js\"",
          "timeout": 5,
          "statusMessage": "Running some other hook..."
        },
        {
          "type": "command",
          "command": "\"~/.claude/hooks/light-hook.sh\" white",
          "timeout": 10
        }
      ]
    }
  ],
  "UserPromptSubmit": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "\"<path-to-node>\" \"~/.claude/hooks/some-other-hook.js\"",
          "timeout": 5,
          "statusMessage": "Running some other hook..."
        },
        {
          "type": "command",
          "command": "\"~/.claude/hooks/light-hook.sh\" green",
          "timeout": 10
        }
      ]
    }
  ],
  "PreToolUse": [
    {
      "matcher": "Bash",
      "hooks": [
        {
          "type": "command",
          "command": "rtk hook claude"
        }
      ]
    },
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "\"~/.claude/hooks/light-hook.sh\" green",
          "timeout": 10
        }
      ]
    }
  ],
  "Notification": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "\"~/.claude/hooks/light-hook.sh\" notify",
          "timeout": 10
        }
      ]
    }
  ],
  "PermissionRequest": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "\"~/.claude/hooks/light-hook.sh\" red",
          "timeout": 10
        }
      ]
    }
  ],
  "Stop": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "\"~/.claude/hooks/light-hook.sh\" white",
          "timeout": 10
        }
      ]
    }
  ],
  "SessionEnd": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "\"~/.claude/hooks/light-hook.sh\" white",
          "timeout": 10
        }
      ]
    }
  ]
}
```

`light-hook.sh` (10.10.10.100 is my bulbs local IP):

```bash
#!/usr/bin/env bash
set -euo pipefail
COLOR="$1"
INPUT="$(cat)"
AGENT_ID="$(echo "$INPUT" | jq -r '.agent_id // empty')"
if [ -n "$AGENT_ID" ]; then
  exit 0
fi

# "notify" decides from the payload: idle "waiting for your input"
# ping = white (session idle); anything else = red (act now).
if [ "$COLOR" = "notify" ]; then
  MESSAGE="$(echo "$INPUT" | jq -r '.message // empty')"
  case "$MESSAGE" in
    *"waiting for your input"*) COLOR="white" ;;
    *)                          COLOR="red" ;;
  esac
fi

cd /path/to/claude-lightbulb-hooks
exec python3 light.py -q --lan 10.10.10.100 -s on -C "$COLOR" -b 100
```

To wire a new event, add another block calling `light-hook.sh <color>`, or point it straight at `light.py` if you don't need the subagent guard.

## Bulb setup

```bash
pip install tinytuya
```

Copy `light.json.example` to `light.json` and fill in the fields:

```bash
cp light.json.example light.json
```

```json
{
    "device_id": "your-device-id",
    "api_key": "your-tuya-access-id",
    "api_secret": "your-tuya-access-secret",
    "api_region": "in",
    "device_local_key": "your-local-key",
    "device_version": 3.3
}
```

`light.json` is gitignored — never commit it, it holds live credentials.

| Key | Need | How to get |
|---|---|---|
| `device_id` | Always | SmartLife app → bulb → Device Info |
| `api_key` | Cloud | [iot.tuya.com](https://iot.tuya.com) → Cloud → Project → Access ID |
| `api_secret` | Cloud | Same page → Access Secret |
| `api_region` | Cloud | `cn`, `eu`, `eu-w`, `in`, `sg`, `us`, `us-e` |
| `device_local_key` | LAN | iot.tuya.com → Devices → linked device → Local Key |
| `device_version` | LAN | Default `3.3`. Try `3.4` or `3.5` if connection fails |

All fields can live in one config file — unused fields are ignored.

### Getting device_id and local_key

1. Go to [iot.tuya.com](https://iot.tuya.com), sign up, create a Cloud project
2. Cloud → your project → Devices → **Add Device** → paste device ID (from SmartLife app)
3. Device appears with full details including `key` (= `device_local_key`)
4. Note `api_key` and `api_secret` from project's Authorization page

Cloud mode works immediately. LAN mode also needs the bulb IP (use `--lan <ip>`).

## Manual CLI usage

Useful for testing the bulb outside of hooks.

### Cloud mode (default)

Works anywhere with internet — no need to be on same network as bulb.

```bash
# Status
python3 light.py

# Turn on/off
python3 light.py -s on
python3 light.py -s off

# Brightness (0-100%)
python3 light.py -s on -b 70

# Color
python3 light.py -s on -b 50 -C red
python3 light.py -C green
python3 light.py -C '#ff6600'

# Help
python3 light.py -h
```

### LAN mode

Bulb must be on same local network. Faster — no internet round-trip.

```bash
python3 light.py --lan 192.168.1.100 -s on
python3 light.py --lan 192.168.1.100 -b 60 -C yellow
python3 light.py --lan 192.168.1.100 -s off
```

Finding your bulb's IP:
```bash
arp -a | grep esp
# or check router's DHCP client list for MAC matching device_id suffix
```

### Custom config path

```bash
python3 light.py -c /path/to/config.json -s on
```

## Available colors

| Name | Name | Name |
|---|---|---|
| `red` | `green` | `yellow` |
| `blue` | `orange` | `purple` |
| `pink` | `cyan` | `white` |
| `warmwhite` | | |

Hex accepted: `#ff0000`, `#f00`, `#00ff00`, etc.

## Troubleshooting

**Cloud: "permission deny" (1106)** — device not linked to cloud project. Go to iot.tuya.com → Devices → Add Device → enter device ID.

**LAN: "Unable to Connect" (901)** — bulb not reachable. Check IP, network isolation, or Wi-Fi client isolation on your router. Fall back to cloud mode.

**Light doesn't match session state / flickers to wrong color** — check whether a subagent fired the hook. `light-hook.sh` should skip when `agent_id` is present in stdin JSON; if it's not skipping, verify `jq` is installed and on `PATH`.

**Light stuck red while Claude is clearly working** — you're missing the `PreToolUse` → green wiring. During a long turn nothing re-fires `UserPromptSubmit`, so a mid-turn red never resets. Add the `PreToolUse` block (see [Why `PreToolUse` is needed](#why-pretooluse-is-needed)).

## Reference

- [Claude Code hooks docs](https://code.claude.com/docs/en/hooks.md)
