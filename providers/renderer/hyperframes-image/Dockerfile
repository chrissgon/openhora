# The image the HyperFrames engine of renderer:video draws in (package V3a-image). hf_image.py, beside this file, builds it with
# `build --confirmed`, one command the person starts; nothing in the repository builds or pulls it by itself, and a job never pulls anything.
#
# Third-party code (HyperFrames, GSAP and their npm dependencies, a static ffmpeg, Chrome for Testing's headless shell) is installed and run
# only in here, never on the host. The network exists only while this image is built: every job runs it with no network, a read-only root,
# every capability dropped, no new privileges and a non-root user (providers/_container.py argv).
#
# What is pinned, and how. The values are in pins.json; hf_image.py passes those of the docker daemon's architecture as build arguments, so a
# plain `docker build` of this folder stops at the first RUN below.
#   - the base image, by the digest of its multi-architecture index (node:22.23.4-bookworm-slim; HyperFrames 0.9.19 needs Node.js 22 or later);
#   - the package index, by a dated snapshot of the Debian archive (apt checks the archive's signature, so plain http is enough);
#   - Chrome for Testing's headless shell, by version and by the archive's size, md5 and sha256 for each architecture (_fetch_browser.py
#     refuses an archive that differs from any of the three);
#   - a static ffmpeg build (the one HyperFrames 0.9.19 itself pins), by the archive's sha256 for each architecture (fetch_ffmpeg.py);
#   - HyperFrames, GSAP and every package they need, from package-lock.json: exact versions and an integrity hash for each package, installed
#     with `npm ci --ignore-scripts`, so no dependency's install script runs;
#   - the three fonts a render may draw with (Inter 500 and 800, JetBrains Mono 500; SIL OFL 1.1), copied from fonts/ and checked against
#     fonts/SHA256SUMS. No system font package is left: the last RUN purges the one apt pulls in and fails the build when any other font
#     file is found outside HyperFrames' own node_modules (those are listed in /opt/hf-build/node-modules-font-files.txt).
# Telemetry is off from the first layer on (HYPERFRAMES_NO_TELEMETRY=1, DO_NOT_TRACK=1). HyperFrames' commands that reach a network or an
# account (upgrade, update, skills) are never called, at build time or at run time.
# The image records its pins in labels and its installed npm tree in /opt/hf/npm-ls.txt.

# node:22.23.4-bookworm-slim
FROM node:22.23.4-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d

ARG DEBIAN_FRONTEND=noninteractive
ARG DEFINITION_HASH=unset
ARG DEBIAN_SNAPSHOT
ARG CHROME_VERSION
ARG CHROME_URL
ARG CHROME_SIZE
ARG CHROME_MD5
ARG CHROME_SHA256
ARG CHROME_BINARY
ARG FFMPEG_URL
ARG FFMPEG_SHA256
ARG FFMPEG_VERSION
ARG HYPERFRAMES_VERSION
ARG GSAP_VERSION

ENV HYPERFRAMES_NO_TELEMETRY=1 \
    DO_NOT_TRACK=1 \
    NPM_CONFIG_UPDATE_NOTIFIER=false

# Every pin must be given: hf_image.py build passes all of them, from pins.json.
RUN for value in "$DEBIAN_SNAPSHOT" "$CHROME_VERSION" "$CHROME_URL" "$CHROME_SIZE" "$CHROME_MD5" "$CHROME_SHA256" "$CHROME_BINARY" \
                 "$FFMPEG_URL" "$FFMPEG_SHA256" "$FFMPEG_VERSION" "$HYPERFRAMES_VERSION" "$GSAP_VERSION"; do \
      [ -n "$value" ] || { echo "a pin is missing: build this image with hf_image.py build --confirmed, which reads pins.json" >&2; exit 1; }; \
    done

# The libraries the headless shell links against, and python3 for the two download scripts, from the dated snapshot. fontconfig-config, which
# libpango pulls in, depends on a font package (fonts-dejavu-core): the last RUN purges it.
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

# The browser: downloaded from the official Chrome for Testing storage by _fetch_browser.py, which refuses an archive whose size, md5 or
# sha256 differs from the pin, unpacks it with no member outside the folder and no link, and removes the archive.
COPY _fetch_browser.py /opt/hf-build/_fetch_browser.py
RUN python3 -I /opt/hf-build/_fetch_browser.py "${CHROME_URL}" "${CHROME_SIZE}" "${CHROME_MD5}" "${CHROME_SHA256}" /opt/chrome "${CHROME_BINARY}" \
    && chmod 0755 "/opt/chrome/${CHROME_BINARY}" && ln -s "/opt/chrome/${CHROME_BINARY}" /opt/chrome/chrome-headless-shell \
    && ! ldd /opt/chrome/chrome-headless-shell | grep -q "not found" \
    && /opt/chrome/chrome-headless-shell --version | grep -q -F "${CHROME_VERSION}"

# ffmpeg and ffprobe: the static build's archive, checked against its sha256; only the two programs are unpacked.
COPY fetch_ffmpeg.py /opt/hf-build/fetch_ffmpeg.py
RUN python3 -I /opt/hf-build/fetch_ffmpeg.py "${FFMPEG_URL}" "${FFMPEG_SHA256}" /usr/local/bin \
    && ffmpeg -version | grep -q -F "ffmpeg version ${FFMPEG_VERSION}" \
    && ffprobe -version | grep -q -F "ffprobe version ${FFMPEG_VERSION}"

# HyperFrames and GSAP: the lockfile decides every byte (integrity hashes); --ignore-scripts keeps every dependency's install script from
# running. The versions installed must be the pinned ones.
WORKDIR /opt/hf
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund \
    && npm ls --all --parseable > /opt/hf/npm-ls.txt \
    && test "$(node -p "require('/opt/hf/node_modules/hyperframes/package.json').version")" = "${HYPERFRAMES_VERSION}" \
    && test "$(node -p "require('/opt/hf/node_modules/gsap/package.json').version")" = "${GSAP_VERSION}" \
    && rm -rf /root/.npm

# The three fonts a render may draw with, and their licences (SIL OFL 1.1 asks for its text to travel with the fonts).
COPY fonts/ /opt/fonts/
RUN cd /opt/fonts && sha256sum -c --strict SHA256SUMS

# Hook for V3b: the HyperFrames registry files of the committed allowlist go here, before the user and the font purge, so that the purge
# covers them too. V3b adds registry.sha256 and fetch_registry.py to this folder, lists both in manifest.json and in .dockerignore, and
# inserts these two lines at this place:
#   COPY registry.sha256 fetch_registry.py /opt/hf-build/
#   RUN python3 -I /opt/hf-build/fetch_registry.py /opt/hf-build/registry.sha256 /opt/hf-registry
# The definition's hash then changes, so this image alone is rebuilt: the ffmpeg engine's image does not hash these files.

# The user a job runs as (on Linux a job runs with the caller's numeric user instead: providers/_container.py argv).
RUN useradd --system --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin hf

# The last RUN: purge the font package apt pulled in, then fail the build when a font file other than the three of /opt/fonts is left
# outside HyperFrames' own node_modules. The ones inside node_modules are listed for the record: the code guard of condition C5
# (check_fonts, package V3a), not this layer, keeps a page from using them.
RUN dpkg --purge --force-depends fonts-dejavu-core \
    && rm -rf /usr/share/fonts /var/cache/fontconfig \
    && (dpkg -l | awk '$1=="ii"{print $2}' | grep -E '^fonts-' || true) > /opt/hf-build/system-font-packages.txt \
    && test ! -s /opt/hf-build/system-font-packages.txt \
    && find / -xdev -type f \( -iname '*.ttf' -o -iname '*.ttc' -o -iname '*.otf' -o -iname '*.otc' -o -iname '*.woff' -o -iname '*.woff2' \
         -o -iname '*.pfa' -o -iname '*.pfb' -o -iname '*.pcf' -o -iname '*.pcf.gz' -o -iname '*.bdf' \) -print \
       | LC_ALL=C sort > /opt/hf-build/all-font-files.txt \
    && awk 'index($0, "/opt/hf/node_modules/") != 1' /opt/hf-build/all-font-files.txt > /opt/hf-build/font-files.txt \
    && awk 'index($0, "/opt/hf/node_modules/") == 1' /opt/hf-build/all-font-files.txt > /opt/hf-build/node-modules-font-files.txt \
    && printf '%s\n' /opt/fonts/inter-500.woff2 /opt/fonts/inter-800.woff2 /opt/fonts/jetbrains-mono-500.woff2 > /opt/hf-build/font-files.expected \
    && diff /opt/hf-build/font-files.expected /opt/hf-build/font-files.txt

# The inner entry of the provider (V3a-2): copied after the purge, so no RUN follows it.
COPY hf_render.py /opt/hf-run/hf_render.py

LABEL org.openhora.component="renderer-hyperframes" \
      org.openhora.definition="${DEFINITION_HASH}" \
      org.openhora.base="node:22.23.4-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d" \
      org.openhora.debian-snapshot="${DEBIAN_SNAPSHOT}" \
      org.openhora.chrome.version="${CHROME_VERSION}" \
      org.openhora.chrome.sha256="${CHROME_SHA256}" \
      org.openhora.ffmpeg.version="${FFMPEG_VERSION}" \
      org.openhora.ffmpeg.sha256="${FFMPEG_SHA256}" \
      org.openhora.hyperframes.version="${HYPERFRAMES_VERSION}" \
      org.openhora.gsap.version="${GSAP_VERSION}"

ENV HOME=/tmp \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    CI=1 \
    PRODUCER_HEADLESS_SHELL_PATH=/opt/chrome/chrome-headless-shell \
    PUPPETEER_EXECUTABLE_PATH=/opt/chrome/chrome-headless-shell \
    PATH=/opt/hf/node_modules/.bin:$PATH

USER 10001:10001
WORKDIR /work
