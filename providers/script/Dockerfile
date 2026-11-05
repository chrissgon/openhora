# The image a project script runs in, its dependencies are built in, and its per-step egress proxy runs in (providers/script/container.py
# builds it with `build --confirmed`, one command the person starts; nothing in the repository builds or pulls it by itself, and a
# script run never pulls anything). One image, three roles, told apart by the command the host gives it:
#   python3 -I /opt/script/_inner.py run --kind py|sh     the script (the script file and the installed dependencies are read-only)
#   python3 -I /opt/script/_inner.py build                the dependency build (a lock file on standard input, no mount)
#   python3 -I /opt/script/egress_proxy.py ...            the egress proxy of one step (CONNECT to declared host:port pairs only)
# The proxy shares the image on purpose: its code is a file of this definition, so it is built locally from a definition that is pinned,
# never pulled at run time, and the one hash below names it.
#
# What is pinned, and how (the same as the converter's image, providers/converter/Dockerfile):
#   - the base image, by the digest of its multi-architecture index (debian:bookworm-20261005-slim);
#   - the package index, by a dated snapshot of the Debian archive: the same build tomorrow installs the same versions (apt checks the
#     archive's signature, so plain http is enough before the certificates are installed).
# The image holds python3 and pip (the dependency build needs pip; a run has no network to use it with), bash and the usual tools, curl and
# the certificates; no compiler, no credential, no shell history. /deps is world-writable ONLY so that the unprivileged build can fill it:
# a run mounts the root file system read-only, so /deps is read-only there.
#
# At run time the host starts it with no network (or only the internal network of the step), a read-only root file system, every
# capability dropped, no new privileges, a limit on processes, memory and CPUs, and a memory-backed /tmp and /scratch with no exec
# (providers/_container.py argv; providers/script/container.py). The image records its definition's hash as a label.

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
      python3 python3-pip ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt /var/log/apt /var/log/dpkg.log \
    && mkdir -p /opt/script /deps /in && chmod 0777 /deps

COPY _inner.py egress_proxy.py /opt/script/

LABEL org.openhora.definition="${DEFINITION_HASH}"
USER 65534:65534
WORKDIR /scratch
