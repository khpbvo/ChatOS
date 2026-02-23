# ChatOS systemd Services

## Service Units

- **chatos-agent.service** — Agent WebSocket server (runs as `_chatos`)
- **chatos-ui.service** — Kiosk browser (depends on agent)

## Installation

Units are installed automatically by `deploy/install.sh` to `/etc/systemd/system/`.

## Overrides

To customize service flags without modifying the unit file:

```bash
sudo systemctl edit chatos-agent.service
```

Example override (change port and model):
```ini
[Service]
ExecStart=
ExecStart=/usr/local/share/chatos/venv/bin/python -m src --serve --port 9000 --model opus --rules /etc/chatos/rules.toml --log-dir /var/chatos/logs --home-dir /home/agent01 --static-dir /usr/local/share/chatos/ui/dist --cli-path /home/agent01/.npm-global/bin/claude
```

## API Key

Set in `/etc/chatos/env` (root:_chatos 640), NOT in the unit file.
The Python app reads `/etc/chatos/env` at startup before spawning the SDK.
