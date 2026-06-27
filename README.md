# lcn2mqtt

Async bridge between an LCN bus (via LCN-PCHK) and an MQTT broker. Designed to run
as a long-lived service inside a Docker container.

## Features

- LCN status → MQTT (outputs, relays, LEDs, binary sensors, variables, setpoints, thresholds, motor positions)
- MQTT → LCN commands (outputs, relays, LEDs, motors, variables, setpoints)
- Home Assistant MQTT Discovery support
- Pure asyncio, single process: [`pypck`](https://pypi.org/project/pypck/) + [`aiomqtt`](https://pypi.org/project/aiomqtt/)
- Configuration via `data/configuration.yaml` and/or environment variables / `.env`

## Topic schema

The bridge identifier (default `lcn2mqtt`) is used as the MQTT topic prefix and is
configurable via `LCN2MQTT_IDENTIFIER`. All per-module topics follow the prefix
`<id>/module/<seg>/<addr>`.

State topics (published, retained):

| Topic | Payload |
| --- | --- |
| `<id>/module/<seg>/<addr>/output/<1-4>/state` | `on` / `off` |
| `<id>/module/<seg>/<addr>/output/<1-4>/brightness` | brightness `0`–`100` (float) |
| `<id>/module/<seg>/<addr>/relay/<1-8>/state` | `on` / `off` |
| `<id>/module/<seg>/<addr>/led/<1-12>/state` | `on` / `off` / `blink` / `flicker` |
| `<id>/module/<seg>/<addr>/binsensor/<1-8>/state` | `on` / `off` |
| `<id>/module/<seg>/<addr>/variable/<1-12>/state` | value (in configured unit) |
| `<id>/module/<seg>/<addr>/setpoint/<1-2>/state` | value (in configured unit) |
| `<id>/module/<seg>/<addr>/setpoint/<1-2>/locked` | `on` / `off` |
| `<id>/module/<seg>/<addr>/threshold/<reg>/<1-5>/state` | value (in configured unit) |
| `<id>/module/<seg>/<addr>/motor_relays/<1-4>/state` | `open` / `closed` / `opening` / `closing` / `stop` |
| `<id>/bridge/status` | `online` / `offline` (LWT) |

Command topics (subscribed):

| Topic | Payload |
| --- | --- |
| `<id>/module/<seg>/<addr>/output/<1-4>/set` | `0`–`100`, `on`, `off` |
| `<id>/module/<seg>/<addr>/output/<1-4>/set_brightness` | `0`–`100` |
| `<id>/module/<seg>/<addr>/output/<1-4>/set_transition` | transition time in ms |
| `<id>/module/<seg>/<addr>/relay/<1-8>/set` | `on`, `off`, `toggle` |
| `<id>/module/<seg>/<addr>/led/<1-12>/set` | `on`, `off`, `blink`, `flicker` |
| `<id>/module/<seg>/<addr>/variable/<1-12>/set` | value (in configured unit) |
| `<id>/module/<seg>/<addr>/variable/<1-12>/shift` | delta (in configured unit) |
| `<id>/module/<seg>/<addr>/setpoint/<1-2>/set` | value (in configured unit) |
| `<id>/module/<seg>/<addr>/setpoint/<1-2>/shift` | delta from current value |
| `<id>/module/<seg>/<addr>/setpoint/<1-2>/offset` | delta from programmed value |
| `<id>/module/<seg>/<addr>/setpoint/<1-2>/lock` | `on`, `off` |
| `<id>/module/<seg>/<addr>/motor_relays/<1-4>/set` | `open`/`up`, `close`/`down`, `stop` |

## Configuration

Configuration is loaded from `data/configuration.yaml`. Values can be overridden with
environment variables (prefix `LCN2MQTT_`, nested delimiter `_`) or a `.env` file.

#### `data/configuration.yaml`

```yaml
lcn:
  host: 192.168.1.40
  port: 4114
  username: lcn
  password: ****
  dim_mode: STEPS200
  sk_num_tries: 0
  acknowledge_commands: false

mqtt:
  host: mqtt.local
  port: 1883
  username: mqtt
  password: ****

devices:
  m000007:                   # module address (m<seg><addr>)
    output1:
      transition: 0          # default transition time in ms

    variable1:
      unit: "celsius"        # variable unit (celsius, lux, percent, native, ...)

    setpoint1:
      unit: "celsius"

    homeassistant:                 # Publish MQTT discovery messages for Home Assistant
      include: [output1, relay1]   # auto-expose these ports (supports wildcards)
      exclude: [relay2]            # remove from include

      # Manual component definitions.
      # Additonal settings will be used for discovery messages
      # (see https://www.home-assistant.io/integrations/mqtt/discovery-messages).
      binary_sensors:
        door_sensor:
          name: "Door Sensor"
          source: binsensor1

      sensors:
        temp:
          name: "Temperature"
          source: variable1

      switches:
        pump:
          name: "Water Pump"
          target: relay1

      lights:
        bedroom:
          name: "Bedroom Light"
          target: output1

      covers:
        blind:
          name: "Blind"
          target: motor1

      climates:
        thermostat:
          name: "Thermostat"
          temperature: setpoint1
          current_temperature: variable1

homeassistant:
  enabled: true            # enable Home Assistant MQTT Discovery
  scan_modules: true       # scan bus for modules on startup

log_level: "INFO"
```

When `homeassistant.include` is omitted for a device, `output1`, `output2`, `relay1`–`relay8`
are exposed by default. Supported platforms are `binary_sensors`, `sensors`, `switches`, `lights`, `numbers`, `selects`, `covers`, or `climates`.

### Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `LCN2MQTT_IDENTIFIER` | `lcn2mqtt` | MQTT topic prefix / bridge identifier |
| `LCN2MQTT_LCN_HOST` | — | LCN-PCHK hostname or IP |
| `LCN2MQTT_LCN_PORT` | `4114` | LCN-PCHK port |
| `LCN2MQTT_LCN_USERNAME` | — | LCN-PCHK username |
| `LCN2MQTT_LCN_PASSWORD` | — | LCN-PCHK password |
| `LCN2MQTT_LCN_DIM_MODE` | `STEPS200` | Dimming mode (`STEPS50` or `STEPS200`) |
| `LCN2MQTT_LCN_SK_NUM_TRIES` | `0` | Segment coupler scan retries |
| `LCN2MQTT_LCN_ACKNOWLEDGE_COMMANDS` | `false` | Request command acknowledgement |
| `LCN2MQTT_MQTT_HOST` | — | MQTT broker hostname or IP |
| `LCN2MQTT_MQTT_PORT` | `1883` | MQTT broker port |
| `LCN2MQTT_MQTT_USERNAME` | — | MQTT username (optional) |
| `LCN2MQTT_MQTT_PASSWORD` | — | MQTT password (optional) |
| `LCN2MQTT_MQTT_QOS` | `0` | MQTT QoS level |
| `LCN2MQTT_HOMEASSISTANT_ENABLED` | `false` | Enable HA MQTT Discovery |
| `LCN2MQTT_HOMEASSISTANT_PREFIX` | `homeassistant` | HA discovery prefix |
| `LCN2MQTT_HOMEASSISTANT_SCAN_MODULES` | `true` | Scan bus for modules on startup |
| `LCN2MQTT_LOG_LEVEL` | `INFO` | Log level |

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
