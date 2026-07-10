# Deploying the Blockless API gateway

This repository is the stateless **control-plane gateway**. Production runs it on
Kubernetes via Helm, in front of the inference, knowledge-graph, constraint-router,
and simulation services (each their own deployment). A single-service **Render**
blueprint is provided for staging and demos.

## Architecture recap

The gateway holds no model weights and no catalog data — it authenticates, meters, and
dispatches over gRPC to the backing tiers. Because it is stateless (signed session
tokens, Redis-backed counters), it scales horizontally behind an HPA; the GPU inference
tier and the solver/simulation tiers scale independently.

```text
            ┌──────────────┐      gRPC      ┌────────────────────────┐
 browser ─► │  gateway     │ ─────────────► │ inference (vLLM, GPU)   │
   SSE      │ (this repo)  │ ─────────────► │ knowledge graph (Neo4j) │
            │  FastAPI/CPU │ ─────────────► │ constraint router       │
            └──────┬───────┘ ─────────────► │ sim kernel · enclosure  │
                   │                         └────────────────────────┘
             PostgreSQL (projects, telemetry) · Redis · Kafka
```

## Production (Kubernetes + Helm)

1. Provision the datastores (managed Postgres, Neo4j Aura or self-hosted, Redis, Kafka).
2. Deploy the backing services from their own charts (`inference`, `knowledge-graph`,
   `constraint-router`, `sim-kernel`, `enclosure`). The inference chart requires a GPU
   node pool.
3. Deploy the gateway chart, pointing it at the mesh:

   ```bash
   helm upgrade --install blockless-api ./charts/gateway \
     --set env.INFERENCE_GRPC_ENDPOINT=grpc://inference:9000 \
     --set env.KNOWLEDGE_GRAPH_URI=bolt://neo4j:7687 \
     --set env.CONSTRAINT_ROUTER_ENDPOINT=grpc://router:9100 \
     --set env.SIM_KERNEL_ENDPOINT=grpc://sim:9200 \
     --set env.REDIS_URL=redis://redis:6379/0 \
     --set env.KAFKA_BROKERS=kafka:9092 \
     --set secrets.DATABASE_URL=... \
     --set secrets.MPYHW_GOOGLE_CLIENT_ID=... \
     --set secrets.MPYHW_GOOGLE_CLIENT_SECRET=...
   ```

Use `/v1/health/ready` as the readiness probe — it verifies database connectivity and
that the required mesh endpoints resolve before the pod accepts traffic. An HPA on CPU
handles gateway scale-out.

Google OAuth must include the callback URL for each environment:

```text
https://<your-host>/v1/auth/google/callback
```

In Google Cloud Console, use an OAuth client of type **Web application**, with the
deployment host as an authorized JavaScript origin and `.../v1/auth/google/callback`
as the redirect URI.

## Staging / demo (Render)

For a quick single-service staging environment, sync the Blueprint from
[`render.yaml`](render.yaml):

1. Push this repo to GitHub.
2. In Render, create or sync the Blueprint. Set the secret values when prompted:
   - `INFERENCE_GRPC_ENDPOINT` (or `DEEPSEEK_API_KEY` for the dev fallback)
   - `MPYHW_GOOGLE_CLIENT_ID`
   - `MPYHW_GOOGLE_CLIENT_SECRET`

The Blueprint provisions the web service + a Postgres instance, injects `DATABASE_URL`,
generates `MPYHW_JWT_SECRET`, and sets `MPYHW_ENV=prod`. On the starter plan the gateway
runs a single instance; because it is stateless it can be scaled up freely on a paid plan.

```text
https://blockless-web-api.onrender.com
```

## Local image smoke test

```sh
docker build -t blockless-api .
docker run --rm -p 8080:8080 \
  -e DATABASE_URL="postgresql://postgres:postgres@host.docker.internal:5432/mpyhw_test" \
  -e MPYHW_ENV=prod -e MPYHW_JWT_SECRET=x -e DEEPSEEK_API_KEY=y \
  -e MPYHW_GOOGLE_CLIENT_ID=google-client-id -e MPYHW_GOOGLE_CLIENT_SECRET=google-client-secret \
  blockless-api
curl localhost:8080/v1/health
curl localhost:8080/v1/health/ready
curl localhost:8080/v1/boards
```

For the full end-to-end stack (Postgres, Neo4j, Redis, Kafka, service stubs), use the
`docker compose --profile local up` workflow described in the root [`README.md`](README.md).
