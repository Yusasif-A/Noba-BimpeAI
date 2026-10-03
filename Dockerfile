
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements before the source, so editing a prompt does not reinstall
# PyTorch. This layer only rebuilds when requirements.txt itself changes.
COPY requirements.lock ./

# --no-deps, and an exact list, because this set cannot be resolved.
#
# livekit-agents 1.0.11 requires types-protobuf<5. Every livekit-protocol
# release that livekit-api 1.2.1 will accept requires >=5. There is no version
# of anything that satisfies both, so pip stops with ResolutionImpossible no
# matter how the constraints are arranged - and it is right to, by its own
# rules.
#
# It runs anyway, because types-protobuf ships type-checker stubs and no runtime
# code at all. The contradiction is invisible to anything that executes.
#
# So the container is told what to install rather than asked to work it out.
# requirements.lock is the transitive closure of the working environment, exact
# versions, generated from a machine where the agents actually run. Nothing is
# resolved, so nothing can drift and nothing can conflict.
RUN pip install --no-cache-dir --no-deps -r requirements.lock

RUN useradd --create-home --uid 1000 noba     && mkdir -p /app/state     && chown -R noba:noba /app
COPY --chown=noba:noba . .
USER noba
RUN python agent.py download-files

CMD ["python", "agent.py", "start"]
