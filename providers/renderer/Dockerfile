# The image the renderer runs in (providers/renderer/ffmpeg.py builds it with `build --confirmed`, one command the person starts;
# nothing in the repository builds or pulls it by itself, and nothing downloads a browser any other way).
#
# What is pinned, and how:
#   - the base image, by the digest of its multi-architecture index (the tag it came from is in the comment; the digest is the
#     pin). The same base as the transcriber's image. Read from the registry's metadata on 2026-10-13, nothing was pulled;
#   - the package index, by a dated snapshot of the Debian archive (the same build tomorrow installs the same versions; apt checks
#     the archive's signature, so plain http is enough before the certificates are installed);
#   - Chrome for Testing's headless shell, by version AND by the archive's size, md5 and sha256 (browser-pin.json: the size and md5
#     are the official storage bucket's own metadata, the sha256 was computed once by the maintainer's `pin-browser`). The build
#     stops when the archive it downloads differs from any of the three. `build` passes them as build arguments and refuses
#     to start while the sha256 is not pinned.
# The image records its versions in labels (the definition's hash, the base digest, the snapshot, Chrome's version) and in
# /opt/renderer/versions.json (what `_inner.py selfcheck` printed at build time: ffmpeg, python, the browser); the host's `--check` runs `_inner.py selfcheck` and prints them.
#
# What the image holds: ffmpeg (with ffprobe), python3, a minimal free font (DejaVu), the pinned headless shell, and the renderer's
# own modules, templates and data. No compiler, no shell history, a non-root user. At run time the host starts it with no network, a
# read-only root file system, every capability dropped and no environment (see _docker.py, "The container").
#
# The browser's sandbox. Chrome's own sandbox needs user namespaces, which `--cap-drop ALL` and `no-new-privileges` (and Docker's
# default seccomp profile) take away, so the headless shell runs with --no-sandbox INSIDE this image only, and the container is the
# boundary instead: no network, a read-only root, no capability, a non-root user, a pids/memory/cpu limit, only normalised image
# assets and the pinned templates reach the page, every page request is answered from memory or failed, and a content security
# policy is set. _cdp.container_mode() turns it on only where this file's marker exists and RENDERER_IN_CONTAINER is 1; on the host
# the sandbox is on and there is no retry. The render's result says which (`browser_sandbox`).

# debian:bookworm-20261005-slim
FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20261006T000000Z
# Set by `build --confirmed` from browser-pin.json for the daemon's architecture, and the hash of this folder's definition.
ARG DEFINITION_HASH=unset
ARG CHROME_VERSION
ARG CHROME_URL
ARG CHROME_SIZE
ARG CHROME_MD5
ARG CHROME_SHA256
ARG CHROME_BINARY

# The libraries the headless shell links against (the build stops below when one is missing, instead of at the first render).
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

# The browser: downloaded from the official Chrome for Testing storage by _fetch_browser.py, which refuses an archive whose size,
# md5 or sha256 differs from the pin, unpacks it with no member outside the folder and no link, and removes the archive.
COPY _fetch_browser.py /opt/renderer/_fetch_browser.py
RUN test -n "${CHROME_URL}" -a -n "${CHROME_SHA256}" -a -n "${CHROME_MD5}" -a -n "${CHROME_SIZE}" \
      || { echo "browser-pin.json has no sha256 for this architecture: run pin-browser --confirmed first" >&2; exit 1; } \
    && python3 -I /opt/renderer/_fetch_browser.py "${CHROME_URL}" "${CHROME_SIZE}" "${CHROME_MD5}" "${CHROME_SHA256}" /opt/chrome "${CHROME_BINARY}" \
    && chmod 0755 "/opt/chrome/${CHROME_BINARY}" && ln -s "/opt/chrome/${CHROME_BINARY}" /opt/chrome/chrome-headless-shell \
    && ! ldd /opt/chrome/chrome-headless-shell | grep -q "not found" \
    && /opt/chrome/chrome-headless-shell --version | grep -q "${CHROME_VERSION}"

ENV RENDERER_IN_CONTAINER=1 \
    RENDERER_BROWSER=/opt/chrome/chrome-headless-shell \
    HOME=/tmp \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0

COPY . /opt/renderer/
RUN chmod -R go-w /opt/renderer \
    && printf '%s\n' "openhora renderer image" > /etc/openhora-renderer-image \
    && useradd --system --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin renderer \
    && python3 -I /opt/renderer/_inner.py --result /opt/renderer/versions.json selfcheck

LABEL org.openhora.component="renderer" \
      org.openhora.chrome.version="${CHROME_VERSION}" \
      org.openhora.chrome.sha256="${CHROME_SHA256}" \
      org.openhora.debian-snapshot="${DEBIAN_SNAPSHOT}" \
      org.openhora.base="debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587" \
      org.openhora.definition="${DEFINITION_HASH}"

USER 10001:10001
WORKDIR /scratch
ENTRYPOINT ["python3", "-I", "/opt/renderer/_inner.py"]
