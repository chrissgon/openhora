# The image the document converter runs in (providers/converter/container.py builds it with `build --confirmed`, one command the
# person starts; nothing in the repository builds or pulls it by itself, and a conversion never pulls anything).
#
# What is pinned, and how:
#   - the base image, by the digest of its multi-architecture index (debian:bookworm-20261005-slim; the same base the renderer's and
#     the transcriber's definitions pin, read from the registry's metadata and not pulled to be read);
#   - the package index, by a dated snapshot of the Debian archive: the same build tomorrow installs the same versions (apt checks
#     the archive's signature, so plain http is enough before the certificates are installed).
# The tools are adopted and none is rewritten (principle 14): poppler's pdftotext (package poppler-utils), pandoc, and openpyxl
# (package python3-openpyxl) for spreadsheets; the rest is the standard library. The image holds no compiler of its own beyond what
# those packages need to run, no shell history and no credential; it runs as an unprivileged user.
#
# At run time the host starts it with no network, a read-only root file system, every capability dropped, no new privileges, a limit
# on processes, memory and CPUs, a memory-backed /tmp and /scratch with no exec, and the input mounted read-only at /in/input
# (providers/_container.py argv; providers/converter/container.py convert). The image records its definition's hash as a label.

# debian:bookworm-20261005-slim
FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20261006T000000Z
ARG DEFINITION_HASH=unset

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm-updates main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} bookworm-security main" \
      > /etc/apt/sources.list \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends \
      poppler-utils pandoc python3 python3-openpyxl \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log

COPY _inner.py /opt/converter/_inner.py

LABEL org.openhora.definition="${DEFINITION_HASH}"
USER 65534:65534
WORKDIR /scratch
