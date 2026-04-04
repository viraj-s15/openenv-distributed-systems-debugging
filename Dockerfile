FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    redis-server \
    jq \
    procps \
    sqlite3 \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
WORKDIR /home/user/app
RUN mkdir -p /mesh && chown -R user:user /home/user /mesh
USER user

ENV HOME=/home/user
ENV PATH="/home/user/.bun/bin:/home/user/.local/bin:${PATH}"

RUN curl -fsSL https://bun.sh/install | bash

COPY --chown=user:user mesh/ ./mesh/
RUN cd mesh/gateway && bun install
RUN cd mesh/auth && bun install
RUN cd mesh/worker && bun install

COPY --chown=user:user requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user *.py ./
COPY --chown=user:user openenv.yaml ./
COPY --chown=user:user start.sh ./
RUN chmod +x ./start.sh

RUN ln -sfn /home/user/app/mesh /mesh

EXPOSE 8000
CMD ["./start.sh"]
