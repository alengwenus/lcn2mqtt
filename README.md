# lcn2mqtt

Async bridge between an LCN bus (via LCN-PCHK) and an MQTT broker. Designed to run
as a long-lived service inside a Docker container.

## Features

- LCN status -> MQTT (outputs, relays, LEDs, variables, motor positions)
- MQTT -> LCN commands (outputs, relays, motors)
- Pure asyncio, single process: [`pypck`](https://pypi.org/project/pypck/) + [`aiomqtt`](https://pypi.org/project/aiomqtt/)
- Configuration via environment variables

## Topic schema

Base topic is configurable via `MQTT_BASE_TOPIC` (default `/lcn2mqtt`).

State topics (published, retained):

| Topic | Payload |
| --- | --- |
| `/lcn2mqtt/<seg>/<addr>/output/<1-4>` | brightness `0`–`100` (float) |
| `/lcn2mqtt/<seg>/<addr>/relay/<1-8>` | `on` / `off` |
| `/lcn2mqtt/<seg>/<addr>/led/<1-12>` | `on` / `off` / `blink` / `flicker` |
| `/lcn2mqtt/<seg>/<addr>/var/<1-12>` | integer |
| `/lcn2mqtt/<seg>/<addr>/motor/<1-4>` | JSON `{"state","position","tilt"}` |
| `/lcn2mqtt/bridge/status` | `online` / `offline` (LWT) |

Command topics (subscribed):

| Topic | Payload |
| --- | --- |
| `/lcn2mqtt/<seg>/<addr>/output/<1-4>/set` | `0`–`100`, `on`, `off` |
| `/lcn2mqtt/<seg>/<addr>/relay/<1-8>/set` | `on`, `off`, `toggle` |
| `/lcn2mqtt/<seg>/<addr>/motor/<1-4>/set` | `open`/`up`, `close`/`down`, `stop` |

## Configuration

Copy `.env.example` to `.env` and edit:

```
LCN_HOST, LCN_PORT, LCN_USERNAME, LCN_PASSWORD
LCN_MODULES   # comma list, e.g. "0.10,0.11"
MQTT_HOST, MQTT_PORT, MQTT_USERNAME, MQTT_PASSWORD
MQTT_BASE_TOPIC, MQTT_CLIENT_ID, MQTT_QOS, MQTT_RETAIN
LOG_LEVEL
```

## Running locally

```sh
uv sync           # or: pip install -e .
set -a; source .env; set +a
python -m lcn2mqtt
```

## Docker

```sh
docker compose build
docker compose up -d
docker compose logs -f lcn2mqtt
```
