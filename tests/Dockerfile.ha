ARG HA_VERSION=2026.10.4
FROM ghcr.io/home-assistant/home-assistant:${HA_VERSION}
ENTRYPOINT ["python3"]
