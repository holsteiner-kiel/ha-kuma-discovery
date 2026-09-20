FROM ghcr.io/home-assistant/base:3.24

ARG BUILD_VERSION
ARG BUILD_ARCH

RUN apk add --no-cache python3 py3-pip ca-certificates \
    && pip3 install --no-cache-dir --break-system-packages \
       requests==2.32.5 \
       websocket-client==1.8.0 \
       uptime-kuma-api-ng==1.10.0

COPY run.sh /run.sh
COPY app.py /app.py
COPY ha_client.py /ha_client.py
COPY integration_addons.py /integration_addons.py
COPY integration_shelly.py /integration_shelly.py
COPY kuma_monitor.py /kuma_monitor.py
COPY push_state.py /push_state.py
COPY state_store.py /state_store.py

RUN chmod a+x /run.sh

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

CMD ["/run.sh"]
