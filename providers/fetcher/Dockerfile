# The image the reference fetcher runs in (providers/fetcher/ytdlp.py builds it with `build --confirmed`, one command the person
# starts; nothing in the repository builds or pulls it by itself, and nothing downloads the tool any other way).
#
# What is pinned, and how:
#   - the base image, by the digest of its multi-architecture index: the same base, snapshot and package archive as the transcriber's
#     and the renderer's images, so the ffmpeg is the one package version of the common image;
#   - the package index, by a dated snapshot of the Debian archive;
#   - the download tool (yt-dlp, the platform-independent file run by python3), by version, size and sha256 (tool-pin.json). The
#     build passes them as build arguments, stops when the file it downloads differs from any of them, and `build` refuses to start
#     while the pin is not filled. Nothing is installed with pip, at build time or at run time.
#
# What the image holds: python3, ffmpeg (with ffprobe), the CA certificates, the pinned tool file and this folder's own scripts. No compiler,
# a non-root user. The host starts it as three kinds of container (see ytdlp.py): the proxy, the only one with a way out; the fetch, on an
# internal network whose only other member is the proxy; and the measure, with no network at all. Every one has a read-only root file
# system, no capability and no environment variable of the host.

# debian:bookworm-20261005-slim
FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20261006T000000Z
# Set by `build --confirmed` from tool-pin.json and the hash of this folder's definition.
ARG DEFINITION_HASH=unset
ARG TOOL_VERSION
ARG TOOL_URL
ARG TOOL_SIZE
ARG TOOL_SHA256
ARG TOOL_REDIRECT_HOSTS

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm-updates main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} bookworm-security main" \
      > /etc/apt/sources.list \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log

# The tool: downloaded by _fetch_tool.py, which refuses a file whose size or sha256 differs from the pin, follows exactly one redirect and
# only to https on a host of the pin's redirect_hosts, and writes the file read-only.
COPY _fetch_tool.py /opt/fetcher/_fetch_tool.py
RUN test -n "${TOOL_URL}" -a -n "${TOOL_SHA256}" -a -n "${TOOL_SIZE}" -a -n "${TOOL_REDIRECT_HOSTS}" \
      || { echo "tool-pin.json is not filled: run pin-show, then fill the pin from the release's metadata first" >&2; exit 1; } \
    && python3 -I /opt/fetcher/_fetch_tool.py "${TOOL_URL}" "${TOOL_SIZE}" "${TOOL_SHA256}" "${TOOL_REDIRECT_HOSTS}" /opt/fetcher/yt-dlp

ENV HOME=/tmp \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0

COPY . /opt/fetcher/
RUN chmod -R go-w /opt/fetcher \
    && printf '%s\n' "openhora fetcher image" > /etc/openhora-fetcher-image \
    && useradd --system --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin fetcher \
    && python3 -I /opt/fetcher/_fetcher_inner.py --result /opt/fetcher/versions.json selfcheck --expect-version "${TOOL_VERSION}"

LABEL org.openhora.component="fetcher" \
      org.openhora.tool.version="${TOOL_VERSION}" \
      org.openhora.tool.sha256="${TOOL_SHA256}" \
      org.openhora.debian-snapshot="${DEBIAN_SNAPSHOT}" \
      org.openhora.base="debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587" \
      org.openhora.definition="${DEFINITION_HASH}"

USER 10001:10001
WORKDIR /scratch
ENTRYPOINT ["python3", "-I", "/opt/fetcher/_fetcher_inner.py"]
