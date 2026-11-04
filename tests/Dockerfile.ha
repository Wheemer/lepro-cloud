ARG HA_VERSION=2026.10.4
FROM ghcr.io/home-assistant/home-assistant:${HA_VERSION}
RUN python3 -m pip install --no-cache-dir paho-mqtt==2.1.0
ENTRYPOINT ["python3"]
