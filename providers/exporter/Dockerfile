# The image the document renderer runs in (providers/exporter/container.py builds it with `build --confirmed`, one command the person
# starts; nothing in the repository builds or pulls it by itself, and a render never pulls anything). It is the converter's twin for
# the other direction: the converter turns a file into text, the renderer turns a task's text into a CSV file, a workbook, a Word
# document or a PDF.
#
# What is pinned, and how:
#   - the base image, by the digest of its multi-architecture index (debian:bookworm-20261005-slim, the same base as the converter's);
#   - the package index, by a dated snapshot of the Debian archive: the same build tomorrow installs the same versions (apt checks
#     the archive's signature, so plain http is enough before the certificates are installed);
#   - WeasyPrint and what it needs, by requirements.lock: exact versions and the hash of every file pip may take, installed with
#     --require-hashes and --only-binary (a wheel, never a source build, so no compiler is needed and none is installed), into
#     /opt/render/lib, with no dependency resolution at install time.
# The tools are adopted and none is rewritten (principle 14): pandoc (Markdown to the Word document, and to the HTML that is printed),
# openpyxl (package python3-openpyxl) for the workbook, WeasyPrint to print HTML as a PDF with the DejaVu fonts and pango; the rest is
# the standard library. Why WeasyPrint came from the lock and not from the Debian package of the same name: that package depends on
# python3-cffi, which drags in a compiler, the Python headers and a numerical stack, and makes the image three times as large.
# pip is removed once the install is done. The image holds no shell history and no credential; it runs as an unprivileged user.
#
# At run time the host starts it with no network, a read-only root file system, every capability dropped, no new privileges, a limit
# on processes, memory and CPUs, a memory-backed /tmp and /scratch with no exec, and the input mounted read-only at /in/input
# (providers/_container.py argv; providers/exporter/container.py render). The image records its definition's hash as a label.

# debian:bookworm-20261005-slim
FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20261006T000000Z
ARG DEFINITION_HASH=unset

COPY requirements.lock /tmp/requirements.lock

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm-updates main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} bookworm-security main" \
      > /etc/apt/sources.list \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends \
      pandoc python3 python3-openpyxl python3-pip ca-certificates fonts-dejavu-core fontconfig libpango-1.0-0 libpangoft2-1.0-0 \
    && python3 -m pip install --no-cache-dir --break-system-packages --require-hashes --only-binary=:all: --no-deps \
      --target /opt/render/lib -r /tmp/requirements.lock \
    && apt-get purge -y --auto-remove python3-pip \
    && rm -rf /tmp/requirements.lock /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log /root/.cache

COPY _render.py /opt/render/_render.py

LABEL org.openhora.definition="${DEFINITION_HASH}"
USER 65534:65534
WORKDIR /scratch
