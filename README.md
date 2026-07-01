# lcn2mqtt

Async bridge between an LCN bus and an MQTT broker with built-in Home Assistant
MQTT Discovery support. Designed to run as a long-lived service (Docker or Python).

## Features

- Bridge LCN states (outputs, relays, LEDs, sensors, variables) to MQTT
- Send MQTT commands to LCN devices
- Home Assistant MQTT Discovery for automatic entity creation
- Asyncio-based, Docker-friendly

## Quick Example

Create a minimal `.env` with your connection settings and run with Docker Compose:

```bash
LCN2MQTT__LCN__HOST=192.168.1.40
LCN2MQTT__LCN__USERNAME=lcn
LCN2MQTT__LCN__PASSWORD=s3cret
LCN2MQTT__MQTT__HOST=mqtt.local

docker compose up -d
```

MQTT topics use a prefix (default `lcn2mqtt`) and module path, e.g.

```
lcn2mqtt/module/<seg>/<addr>/output/1/state
lcn2mqtt/module/<seg>/<addr>/relay/1/set
```

## Documentation

Full documentation (installation, configuration, topic schema, Home Assistant integration)
is available in the repository [**wiki**](https://github.com/alengwenus/lcn2mqtt/wiki).

## License

MIT — see [LICENSE.md](LICENSE.md)
