ARG HA_VERSION=2026.10.4
FROM ghcr.io/home-assistant/home-assistant:${HA_VERSION}
COPY requirements-runtime.txt /requirements-runtime.txt
RUN python3 -m pip install --no-cache-dir --force-reinstall --require-hashes --no-deps -r /requirements-runtime.txt
ENTRYPOINT ["python3"]
