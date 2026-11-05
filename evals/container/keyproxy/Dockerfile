# The key proxy of the eval network (keyproxy.py): one runs per run, serves that run's one model and holds the
# one key its provider's route file (route-openrouter.json, route-anthropic.json) names, so that no run
# container holds it. evals/executor.py builds it and starts each with its key in its environment, on its
# provider's internal network beside the egress proxy and on the run's own network; its calls to the provider
# leave through that proxy. The meter folder is mounted at /meter for it alone.
FROM alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8
RUN apk add --no-cache python3 ca-certificates \
    && adduser -D -H -s /sbin/nologin keyproxy
COPY keyproxy.py route-*.json /etc/keyproxy/
ENV PYTHONDONTWRITEBYTECODE=1
USER keyproxy
EXPOSE 8890
ENTRYPOINT ["python3", "/etc/keyproxy/keyproxy.py"]
