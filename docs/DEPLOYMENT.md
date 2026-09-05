# Deployment and remote access

Shimmer is designed to run locally. This note records why common "deploy it
to the web" options do or don't fit, and the recommended path if remote
access is ever wanted. Assessed 2026-07.

## Why Cloudflare Pages doesn't work

Cloudflare Pages hosts static files plus lightweight JavaScript edge
functions. Shimmer is a FastAPI server (`shimmer/server.py`) doing heavy
DSP with numpy, scipy, soundfile, and pyloudnorm, plus Demucs stem
separation that uses the local NVIDIA GPU. None of that runs on Pages:

- **No Python runtime for this workload.** Cloudflare's Python support
  (Workers on Pyodide) cannot load soundfile's native libsndfile bindings,
  and Workers enforce CPU-time limits far below what mastering a full
  track — let alone a batch or stem separation — requires.
- **No GPU.** The Remix path shells out to Demucs with CUDA offload.
- **No local filesystem.** Shimmer's workflow is built around reading and
  writing files in the local music library; edge environments have no
  persistent filesystem, so everything would become upload/download.

The same constraints rule out Netlify, Vercel edge functions, and GitHub
Pages.

## Recommended: Cloudflare Tunnel (app stays local)

If the goal is "use Shimmer from another device while it runs on the main
PC," Cloudflare Tunnel (`cloudflared`) is the fit. It proxies a public
HTTPS URL to `localhost:7860` with no port forwarding, no code changes,
and the GPU still doing the work. Free tier is sufficient.

Setup sketch (requires a domain on Cloudflare, free plan is fine):

```
winget install Cloudflare.cloudflared
cloudflared tunnel login
cloudflared tunnel create shimmer
cloudflared tunnel route dns shimmer shimmer.<your-domain>
cloudflared tunnel run --url http://localhost:7860 shimmer
```

For an ad-hoc session without a domain, `cloudflared tunnel --url
http://localhost:7860` prints a temporary `trycloudflare.com` URL.

**Put authentication in front of it.** Shimmer has no login and the API
can read and write files on the host machine. Use Cloudflare Access
(Zero Trust dashboard → Applications) to require an email one-time-code
or identity-provider login before any request reaches the tunnel. Do not
expose a bare tunnel URL publicly.

Also note the server binds to `127.0.0.1` by default (see `start.bat` /
`start.sh`), which is exactly right for tunnel use — the tunnel connects
from the same machine, so nothing needs to listen on the LAN.

## Other options considered

- **Split hosting** — `static/` on Pages, FastAPI backend on a real
  Python host (Fly.io, Railway, a VPS). Works in principle, but costs
  compute, loses the GPU (or pays heavily for one), and requires
  reworking the file-path-based workflow into upload/download. Large
  effort for little gain while the music library lives locally.
- **Pages for a landing/docs page only** — fine at any time; the app
  itself stays local and unaffected.
