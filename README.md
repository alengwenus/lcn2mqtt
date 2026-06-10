# lcn2mqtt

Async bridge between an LCN bus (via LCN-PCHK) and an MQTT broker. Designed to run
as a long-lived service inside a Docker container.

## Features

- LCN status -> MQTT (outputs, relays, LEDs, variables, motor positions)
- MQTT -> LCN commands (outputs, relays, motors)
- Pure asyncio, single process: [`pypck`](https://pypi.org/project/pypck/) + [`aiomqtt`](https://pypi.org/project/aiomqtt/)
- Configuration via environment variables

## Topic schema

Base topic is configurable via `LCN2MQTT_MQTT_BASE_TOPIC` (default `/lcn2mqtt`).

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
LCN2MQTT_LCN_HOST, LCN2MQTT_LCN_PORT, LCN2MQTT_LCN_USERNAME, LCN2MQTT_LCN_PASSWORD
LCN2MQTT_MQTT_HOST, LCN2MQTT_MQTT_PORT, LCN2MQTT_MQTT_USERNAME, LCN2MQTT_MQTT_PASSWORD
LCN2MQTT_MQTT_BASE_TOPIC, LCN2MQTT_MQTT_QOS
LCN2MQTT_LOG_LEVEL
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
