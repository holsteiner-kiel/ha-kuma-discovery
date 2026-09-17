FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION
ARG BUILD_ARCH

RUN apk add --no-cache python3 py3-pip ca-certificates \
    && pip3 install --no-cache-dir --break-system-packages \
       requests==2.32.5 \
       websocket-client==1.8.0 \
       uptime-kuma-api-ng==1.10.0

COPY run.sh /run.sh
COPY app.py /app.py

RUN chmod a+x /run.sh

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

CMD ["/run.sh"]
