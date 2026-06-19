# Deployment notes

How to take this demo from local-first to a public URL, for the specific workload
(Gemma 3n E4B **Q4_0 GGUF** ~4.3 GB + `llama-server`, EmbeddingGemma TFLite retriever,
FastAPI, SQLite) and constraints (low traffic, budget-conscious, **own a domain, no
GPU box**, fidelity to the on-device Q4_0 build matters). Figures are 2026.

## Bottom line

For a budget-conscious, often-idle, fidelity-sensitive demo, **a cheap always-on
CPU VPS is the right answer and lets you skip GPU cost entirely.** The model is
small (~4.3 GB, ~6–8 GB working set), CPU inference is demo-acceptable when tuned,
and a plain VPS gives the cleanest custom-domain + HTTPS story (DNS A-record +
Caddy/Let's Encrypt), no cold start, no per-second metering.

- **Top pick — Hetzner CAX31** (ARM Ampere, 8 vCPU / 16 GB / 160 GB NVMe / 20 TB
  traffic): **€20.99/mo** (+€0.50 IPv4). Always-on, flat cost, EU/GDPR, hourly
  billing (no lock-in). CPU-only is good enough for single-digit users.
- **Runner-up — Modal serverless GPU** (if you want $0-when-idle + snappier latency):
  ~**$0 idle** (4.3 GB model sits free on a Volume; $30/mo starter credit) and
  ~**$8–11/mo** at ~100 req/day on T4/L4. Container-native `llama-server`, seconds
  cold start when weights are on a Volume. Custom domain needs the Team plan — for a
  demo just use the `*.modal.run` HTTPS URL or CNAME via Cloudflare.

## Comparison

| Option | Idle/mo | Active (~100 req/day) | Cold start | GPU/CPU | Custom domain + HTTPS |
|---|---|---|---|---|---|
| **Hetzner CAX31 (CPU, ARM)** ★ | €21 flat | included | none | CPU 8c/16 GB | A-record + Caddy/LE |
| Netcup VPS 2000 G12 (CPU) | €16–19 flat | included | none | CPU 8c/16 GB | A-record + Caddy/LE (12-mo) |
| Contabo VPS 30 (CPU) | ~€15 flat | included | none | CPU 8c/24 GB (oversub.) | A-record + Caddy/LE |
| OVHcloud VPS-4 (CPU) | ~€22 | included | none | CPU /24 GB | A-record + Caddy/LE |
| Oracle Free A1 (CPU) | **$0** | $0 | none | CPU 2 OCPU/12 GB | A-record + Caddy/LE |
| **Modal (serverless GPU)** ☆ | ~$0 | ~$8–11 (T4/L4) | sec (Volume) | GPU T4/L4 | Team plan only |
| Cloud Run + L4 (serverless GPU) | $0 | ~$14 | ~5 s GPU / 15–35 s TTFT | GPU L4 | managed TLS |
| RunPod Serverless | ~$0 | ~$8.55 (L4) | FlashBoot <2 s warm | GPU L4 | endpoint URL (custom unverified) |
| HF Inference Endpoints | ~$0 paused | ~$120–190 realistic | several min | GPU T4/L4 | yes |
| Managed API (e.g. Together) | $0 | cents | none | their GPU | their URL — **breaks Q4_0 fidelity** |

★ top pick ☆ runner-up. **Avoid Fly.io GPU — deprecated after 2026-08-01.**

## Is CPU-only good enough? Mostly yes — two caveats

Realistic numbers for a ~4B-class Q4_0 model on commodity VPS CPUs:
- Decode ~7 tok/s on 4 vCPU, ~12–15 tok/s on 8 vCPU → a 200-token answer ≈ 15–30 s.
- TTFT on a ~1–2k-token RAG prompt ≈ 10–25 s on small x86; faster on ARM (NEON +
  Q4_0 online repacking). To hit a <10 s TTFT bar: keep RAG context ~800–1000 tokens,
  enable prompt caching, quantize the KV cache (q8_0).

- **Caveat A — keep Q4_0 (we already do).** The repacked ARM/x86 kernels (llama.cpp
  ~b4282+, online repacking that replaced static Q4_0_4_4/8_8) give ~2.5–3× prefill /
  ~2× decode. Q4_K_M does **not** reliably get this path — our Q4_0 choice is correct
  for CPU. Build with native flags.
- **Caveat B — Gemma 3n E4B is heavier than its name on CPU, and llama.cpp quality
  may drift.** "E4B" = *effective* 4B but ~8B raw params; the Q4 GGUF is ~4.4 GB, so
  the ~6–8 GB working set is right. The "~3 GB / effective-4B" efficiency comes from
  Per-Layer-Embedding offload in Google's **LiteRT/MediaPipe** runtime, *not*
  llama.cpp. (An open llama.cpp PLE issue, #22243, is filed against **Gemma 4** and is
  **unconfirmed** — it alleges subtly degraded output quality, not an 8B-speed claim.)
  Treat "E4B decodes like 8B on CPU" as a plausible-but-unverified estimate, and
  spot-check output quality. If CPU latency disappoints, a true dense 4B Q4_0 roughly
  halves latency — but that changes the model clinicians are grading, so only if E4B
  fidelity isn't the point.

16 GB RAM is the comfortable target (model ~5 GB resident + ~1–2 GB KV + embedder
~0.3–1 GB + OS). The EmbeddingGemma TFLite retriever (~0.5 s/query) and SQLite cosine
search are CPU-light and fit fine.

## Why Hetzner CAX31 over alternatives

- **vs Oracle Free A1 ($0):** Oracle silently halved the always-free tier to 2 OCPU /
  12 GB (~2026-06-15); 12 GB is borderline, A1 capacity is often unavailable, and
  Oracle reclaims instances idle <20% CPU over 7 days. Fine as a free throwaway only.
- **vs Netcup (€16–19):** slightly cheaper, bigger disk, but 12-month contract vs
  Hetzner's hourly no-lock-in.
- **vs Contabo (~€15):** cheapest sticker / most RAM, but oversubscribed CPU is the
  worst trait for CPU-bound inference and weakest reputation — poor fit for a medical
  demo wanting predictable latency.
- **vs OVHcloud VPS-4 (~€22, 24 GB):** solid EU second choice, more RAM headroom.
- Note: Hetzner **x86** lines got ~150% more expensive on 2026-06-15; the **ARM CAX**
  line is now ~3× cheaper for the same 16 GB — hence CAX31 specifically.

## $0-when-idle GPU path (runner-up)

**Modal** is the cleanest serverless fit: per-second T4 $0.000164 / L4 $0.000222, the
4.3 GB model lives free on a Volume (loads at 1–3 GB/s → seconds, not minutes), native
long-running `llama-server` via `asgi_app`/`http_server`, $30/mo credit, HIPAA-BAA
option. Custom domain needs Team plan — use the `*.modal.run` URL for a demo.
**Cloud Run + L4** (~$14/mo, managed TLS, true scale-to-zero) is the strongest
big-cloud alternative; **RunPod Serverless** (~$8.55/mo, $0 egress, FlashBoot) third.

## Gotchas to design around

- **Cold-start model load:** never download the 4.3 GB GGUF from HF on boot (~35–40 s
  of network, often throttled). **Bake it into the image or put it on a fast
  persistent/network volume**; llama.cpp mmaps so "ready" is near-instant with
  first-token page-in cost. On an always-on VPS this is a non-issue.
- **Egress:** negligible for chat (token payloads are KB); only matters when pulling
  the model on cold starts. Favor always-on (Hetzner: 20 TB included) or $0-egress
  (RunPod). Avoid AWS/GCP egress ($0.09–0.12/GB) if you scale-to-zero and re-pull.
- **GPU availability on cheap tiers:** Vast.ai spot = 15 s interruption notice; RunPod
  community variable; Lambda frequently out of capacity. Avoid spot/community for a
  clinician-facing endpoint. A CPU VPS sidesteps this entirely.
- **Medical ToS:** no host offers a medical carve-out; none gives a HIPAA BAA on
  standard accounts (Modal/RunPod/Cloud Run offer BAAs under agreement) — **don't put
  real PHI on it**; low-sensitivity feedback is fine. Hosted *APIs* are stricter:
  Google's Gemini API terms forbid use "to provide medical advice"; OpenAI forbids
  unlicensed medical advice. Self-hosting the open Gemma weights sidesteps those API
  terms. Keep the in-app "demonstration only, not medical advice" gate regardless.

## Fidelity warning on managed APIs

Together AI appears to serve Gemma 3n E4B (~$0.02 in / $0.04 out per 1M tokens), but
hosted providers serve **their own precision (bf16/fp16/fp8), not our Q4_0 GGUF**.
Quantization is lossy and changes the actual generated tokens. Since the whole point
is clinicians grading the literal outputs of the on-device **Q4_0** build, a
different-quant API answer doesn't validate the shipped model. If offered at all,
label it clearly as not-the-device-model and keep that feedback out of Q4_0 eval.

## Deploy to Hugging Face Spaces (free, first target)

The repo ships a `Dockerfile` (+ `deploy/start.sh`) that builds a single container:
a static CPU `llama-server` + the FastAPI app, with the model assets **baked into
the image at build time** (EmbeddingGemma + Q4_0 GGUF from HF Hub, the v0.3.0 store
from the guidelines GitHub release). The Space's `README.md` YAML header sets
`sdk: docker` and `app_port: 7860`.

```bash
# 1. Log in with a HF token that has WRITE scope
hf auth login

# 2. Create a Docker Space (or make it in the web UI: New Space → Docker → Blank)
hf repo create mamai-demo --repo-type space --space-sdk docker

# 3. Push this repo to the Space; HF builds the Dockerfile and serves it
git remote add space https://huggingface.co/spaces/<hf-username>/mamai-demo
git push space main
```

The first build takes a while (it compiles llama.cpp and downloads ~4.7 GB of
assets). When it finishes the demo is live at
`https://<hf-username>-mamai-demo.hf.space`.

### Free-tier caveats (important)
- **It sleeps after 48 h idle.** The first visitor after a nap waits for the
  container to restart and `llama-server` to load the model (~30–90 s on free CPU).
  Assets are baked into the image, so there is **no** 4.3 GB re-download on wake.
- **Slow generation.** Free CPU is 2 vCPU → ~7 tok/s; a 200-token answer ≈ ~30 s.
  Acceptable for a few clinicians; not a latency benchmark (the UI says so).
- **Feedback is ephemeral on the free tier.** The container filesystem resets on
  restart/rebuild, so `feedback.sqlite` is **lost when the Space sleeps or
  redeploys**. `deploy/start.sh` already writes to `/data/feedback.sqlite` when a
  writable `/data` is mounted — so either add **persistent storage** (paid Spaces
  add-on, mounts `/data`) or wire feedback to a HF **Dataset** repo before relying
  on the collected data. For a first trial, ephemeral is fine.
- **No custom domain on free Spaces.** You get the `*.hf.space` URL. Use your own
  domain on the Oracle Free A1 / Hetzner VPS path below.

## Recommended path

1. **Hetzner CAX31** (€20.99/mo, ARM, 16 GB) as one Docker stack: `llama-server`
   (Q4_0 GGUF, `-t 8`, prompt cache on, KV cache q8_0, RAG context ≤1k tokens) +
   FastAPI/uvicorn + TFLite embedder + SQLite, fronted by **Caddy** for automatic
   HTTPS on your domain. Point an A-record at the box.
2. **Validate before committing:** `llama-bench -m gemma-3n-E4B-it-Q4_0.gguf -t 8
   -p 1500 -n 200` (≈€1 of hourly billing) to confirm TTFT meets your bar.
3. **If $0-idle / snappier latency matters more:** fall back to **Modal** serverless
   (T4/L4, model on a Volume, `*.modal.run` URL), ~$8–11/mo active, ~$0 idle.
4. **Do not** use a managed LLM API as the *evaluated* endpoint (fidelity), and **do
   not** build on Fly.io GPU (deprecated).

### Verification caveats carried through
The "E4B runs like 8B on CPU" speed claim is an unverified extrapolation (the related
llama.cpp PLE issue is unconfirmed and about Gemma 4). Some cheap-provider
egress/cold-start figures are host-stated and unverified. Together's exact serving
precision for 3n E4B is unpublished. The Hetzner June-2026 price hike and Oracle
free-tier halving are confirmed against primary sources.
