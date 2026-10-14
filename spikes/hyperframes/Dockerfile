# SPIKE (not shipped): the image HyperFrames runs in, as a second renderer next to providers/renderer. Third-party code (HyperFrames and
# its npm dependencies) is installed and run only in here, never on the host. The network exists only while this image is built.
#
# What is pinned, and how:
#   - the base image, by the digest of its multi-architecture index (node:22.23.3-bookworm-slim, the tag HyperFrames' own Dockerfile uses);
#   - the Debian package index, by the same dated snapshot as providers/renderer/Dockerfile;
#   - Chrome for Testing's headless shell, by the same version, size, md5 and sha256 as providers/renderer/browser-pin.json, fetched by the same
#     _fetch_browser.py (passed as a named build context, `renderer`), so the browser is the same in both renderers;
#   - HyperFrames and GSAP, by exact version in package.json and by package-lock.json (integrity hashes), installed with `npm ci --ignore-scripts`;
#   - the registry components (HTML files in the HyperFrames repository), by commit and by the sha256 of each file (registry.sha256).
# Build: spikes/hyperframes/build.sh

FROM node:22.23.3-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392

ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20261006T000000Z
ARG CHROME_VERSION
ARG CHROME_URL
ARG CHROME_SIZE
ARG CHROME_MD5
ARG CHROME_SHA256
ARG CHROME_BINARY

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm-updates main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} bookworm-security main" \
      > /etc/apt/sources.list \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg python3 ca-certificates fontconfig fonts-dejavu-core \
      libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libasound2 libpango-1.0-0 libcairo2 \
      libgbm1 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libdrm2 libx11-6 libxext6 libxcb1 \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log

COPY --from=renderer _fetch_browser.py /opt/spike/_fetch_browser.py
RUN test -n "${CHROME_URL}" -a -n "${CHROME_SHA256}" -a -n "${CHROME_MD5}" -a -n "${CHROME_SIZE}" \
    && python3 -I /opt/spike/_fetch_browser.py "${CHROME_URL}" "${CHROME_SIZE}" "${CHROME_MD5}" "${CHROME_SHA256}" /opt/chrome "${CHROME_BINARY}" \
    && chmod 0755 "/opt/chrome/${CHROME_BINARY}" && ln -s "/opt/chrome/${CHROME_BINARY}" /opt/chrome/chrome-headless-shell \
    && ! ldd /opt/chrome/chrome-headless-shell | grep -q "not found" \
    && /opt/chrome/chrome-headless-shell --version | grep -q "${CHROME_VERSION}"

# HyperFrames: the lockfile decides every byte; --ignore-scripts keeps every dependency's install script from running.
WORKDIR /opt/hf
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund && npm ls --all --parseable > /opt/hf/npm-ls.txt

# The registry components (Apache-2.0), fetched from the pinned commit and checked file by file.
COPY registry.sha256 fetch_registry.py ./
RUN python3 -I /opt/hf/fetch_registry.py /opt/hf/registry.sha256 /opt/hf-registry

COPY adapter /opt/adapter

RUN useradd --system --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin hf \
    && printf '%s\n' "hyperframes spike image" > /etc/hf-spike-image \
    && node /opt/hf/node_modules/hyperframes/bin/hyperframes.mjs --version > /opt/hf/version.txt 2>&1 || true

ENV HOME=/tmp \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    HYPERFRAMES_NO_TELEMETRY=1 \
    DO_NOT_TRACK=1 \
    CI=1 \
    PRODUCER_HEADLESS_SHELL_PATH=/opt/chrome/chrome-headless-shell \
    PUPPETEER_EXECUTABLE_PATH=/opt/chrome/chrome-headless-shell \
    PATH=/opt/hf/node_modules/.bin:$PATH

USER 10001:10001
WORKDIR /work
