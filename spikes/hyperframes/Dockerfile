# SPIKE S2 (not shipped): the image HyperFrames 0.9.19 draws in, a second renderer next to providers/renderer. Third-party code (HyperFrames and
# its npm dependencies) is installed and run only in here, never on the host. The network exists only while this image is built.
# Starting point: packages/cli/src/docker/Dockerfile.render of heygen-com/hyperframes at v0.9.19 (commit b4cc674f7f31), with these changes:
#   - the base image is pinned by the digest of its multi-architecture index (node:22.23.4-bookworm-slim, the tag Dockerfile.render uses);
#   - HYPERFRAMES_VERSION is the exact version in package.json, installed from package-lock.json (integrity hashes) with `npm ci --ignore-scripts`,
#     never `npm install -g hyperframes@latest`;
#   - ffmpeg is the static BtbN build Dockerfile.render pins (n8.0.1-66-g27b8d1a017), checked by the same sha256 per architecture;
#   - the browser is Chrome for Testing's headless shell, pinned by version, size, md5 and sha256 like providers/renderer (not Playwright's, not Debian's);
#   - NO system font package (no fonts-*, no fontconfig tools): the only fonts are the three files of the renderer's allow-list, copied by the adapter;
#   - telemetry is off (HYPERFRAMES_NO_TELEMETRY=1, DO_NOT_TRACK=1).
# Build: spikes/hyperframes/build.sh

FROM node:22.23.4-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d

ARG TARGETARCH
ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20261006T000000Z
ARG CHROME_VERSION
ARG CHROME_URL
ARG CHROME_SIZE
ARG CHROME_MD5
ARG CHROME_SHA256
ARG CHROME_BINARY
ARG FFMPEG_RELEASE=https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-02-28-12-59
ARG FFMPEG_BUILD=ffmpeg-n8.0.1-66-g27b8d1a017
ARG FFMPEG_SHA256_AMD64=26d2ecd0cefba99f9d1ea92252a3a4f743a58df4c1c3cf9f8bbaaa40b1fca5b0
ARG FFMPEG_SHA256_ARM64=d72cc324cb65dd92a9ffe699cc95ccbacfef4def8d3ad9fe2b5164a6a71b9595

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm-updates main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} bookworm-security main" \
      > /etc/apt/sources.list \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends \
      python3 ca-certificates \
      libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libasound2 libpango-1.0-0 libcairo2 \
      libgbm1 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libdrm2 libx11-6 libxext6 libxcb1 \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log

COPY --from=renderer _fetch_browser.py /opt/spike/_fetch_browser.py
RUN test -n "${CHROME_URL}" -a -n "${CHROME_SHA256}" -a -n "${CHROME_MD5}" -a -n "${CHROME_SIZE}" \
    && python3 -I /opt/spike/_fetch_browser.py "${CHROME_URL}" "${CHROME_SIZE}" "${CHROME_MD5}" "${CHROME_SHA256}" /opt/chrome "${CHROME_BINARY}" \
    && chmod 0755 "/opt/chrome/${CHROME_BINARY}" && ln -s "/opt/chrome/${CHROME_BINARY}" /opt/chrome/chrome-headless-shell \
    && ! ldd /opt/chrome/chrome-headless-shell | grep -q "not found" \
    && /opt/chrome/chrome-headless-shell --version | grep -q "${CHROME_VERSION}"

COPY fetch_ffmpeg.py /opt/spike/fetch_ffmpeg.py
RUN case "$TARGETARCH" in \
      amd64) FF_ARCH=linux64; FF_SHA256="$FFMPEG_SHA256_AMD64" ;; \
      arm64) FF_ARCH=linuxarm64; FF_SHA256="$FFMPEG_SHA256_ARM64" ;; \
      *) echo "unsupported TARGETARCH '$TARGETARCH'" >&2; exit 1 ;; \
    esac \
    && python3 -I /opt/spike/fetch_ffmpeg.py "$FFMPEG_RELEASE/$FFMPEG_BUILD-$FF_ARCH-gpl-8.0.tar.xz" "$FF_SHA256" /usr/local/bin \
    && ffmpeg -version | grep -F "ffmpeg version ${FFMPEG_BUILD#ffmpeg-}" && ffprobe -version | grep -F "ffprobe version ${FFMPEG_BUILD#ffmpeg-}"

# HyperFrames: the lockfile decides every byte; --ignore-scripts keeps every dependency's install script from running.
WORKDIR /opt/hf
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund && npm ls --all --parseable > /opt/hf/npm-ls.txt

# The registry components (Apache-2.0), fetched from the pinned commit and checked file by file.
COPY registry.sha256 fetch_registry.py ./
RUN python3 -I /opt/hf/fetch_registry.py /opt/hf/registry.sha256 /opt/hf-registry

# fontconfig-config depends on a font package (fonts-dejavu-core) that apt pulls in; the spec allows no system font: purge it and record that none is left.
RUN dpkg --purge --force-depends fonts-dejavu-core && rm -rf /usr/share/fonts /var/cache/fontconfig \
    && (dpkg -l | awk '$1=="ii"{print $2}' | grep -E '^fonts-' || true) > /opt/system-font-packages.txt \
    && test ! -s /opt/system-font-packages.txt && ! find / -xdev \( -name '*.ttf' -o -name '*.otf' -o -name '*.woff*' -o -name '*.pfb' \) -not -path '/opt/hf/node_modules/*' -not -path '/proc/*' | grep -q .

RUN useradd --system --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin hf

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
