# AI Learning Tube

A YouTube-style static site that recommends **only** videos from a short list of trusted channels
(Stanford Online, IBM Technology, NPTEL by default), restricted to AI, LLMs, AI agents, computer vision
and the foundations behind them. Every video is tagged by **topic**, **level** and **format**, ranked by a
**quality score**, and each topic has a **beginner → intermediate → advanced learning path**.
GitHub Actions rebuilds and redeploys it every night.

- No server, no database, no paid services: Python standard library + plain HTML/CSS/JS.
- Only the YouTube Data API (free quota) is called, and only from the nightly build.
- Adding a channel means adding five lines to `config/channels.toml`.

## Set it up (about 10 minutes)

1. **Create a repo** and push this folder to its `main` branch.
2. **Get a YouTube Data API key**
   1. Open <https://console.cloud.google.com/>, create (or pick) a project.
   2. *APIs & Services → Library →* search **YouTube Data API v3** → **Enable**.
   3. *APIs & Services → Credentials → Create credentials → API key*. Under *API restrictions*,
      restrict the key to **YouTube Data API v3**.
3. **Add the key to GitHub:** repo *Settings → Secrets and variables → Actions → New repository secret*,
   name `YOUTUBE_API_KEY`.
4. **Turn on Pages:** repo *Settings → Pages → Build and deployment → Source:* **GitHub Actions**.
5. **Run it once:** *Actions → Nightly build & deploy → Run workflow*. The first run scans every upload
   and playlist of the three channels (≈1–3k quota units; the daily free quota is 10,000) and takes a
   few minutes. After that it runs every night at 07:23 UTC and only fetches what changed.

Your site is at `https://<user>.github.io/<repo>/`. Optionally put that URL in `base_url` in
`config/channels.toml`.

> **Keep the schedule alive.** GitHub pauses scheduled workflows in a public repo after 60 days without
> any commits. If the site stops updating, push any commit or re-enable the workflow under *Actions*.

## Run it locally

Requires Python 3.11+.

```bash
python -m unittest discover -s tests                 # tests (no network)
python -m builder build --fixture tests/fixtures/sample.json   # demo build from sample data
YOUTUBE_API_KEY=... python -m builder build          # real build (writes .state/ and dist/)
python -m builder build --offline                    # rebuild from the cache, no API calls
python -m http.server -d dist 8000                   # open http://localhost:8000
```

Tuning `config/taxonomy.toml` or `config/overrides.toml` and running `--offline` re-tags the whole
catalog from cached metadata without spending quota.

## Add a channel

Append to `config/channels.toml` and push:

```toml
[[channel]]
key = "mit-ocw"                # your own short id
name = "MIT OpenCourseWare"
handle = "@mitocw"             # or channel_id = "UC..." (more robust if the handle ever changes)
weight = 1.0                   # quality prior: 0.8–1.2 is sensible
enabled = true
scan_playlists = true
```

The push triggers a build; the new channel is fully scanned on that run. Its videos still have to pass
the same topic filter, so a general channel only contributes its AI content.

## How it works

```
config/            channels, topic dictionary, curator overrides (TOML)
builder/           Python package run by the workflow
  youtube.py         API client with retries and a hard quota budget
  sync.py            incremental mirror of uploads, playlists and video details
  classify.py        relevance, topic, level and format tagging
  rank.py            quality score
  paths.py           courses (from playlists) and learning paths
  site.py            writes dist/ (site/ assets + data/catalog.json)
site/              the front end (index.html, app.js, styles.css)
tests/             unit + end-to-end tests against an API-shaped fake
```

**Fetching.** Each night the builder reads each channel's uploads list until it reaches videos it already
knows, refreshes the channel's playlist index, re-reads playlists whose item count changed, and fetches
duration/stats for relevant videos whose numbers are older than 20 hours. Everything is cached in
`.state/state.json.gz` (GitHub Actions cache). The YouTube API stops paging an uploads list at roughly
20,000 videos; NPTEL is larger than that, so its older lectures are reached through its course playlists.
If the quota budget runs out mid-scan, the run saves its place and the next night continues.

**Relevance and topics.** Title (×3), tags (×2) and description (×1) are matched against keyword lists
per topic. Description lines containing links and lines repeated across a channel's videos (subscribe
blurbs, copyright notices, "learn more about AI agents →" promos) are ignored. Ambiguous words
("transformer", "agent", "diffusion", "quantization"…) only count, at half weight, when the video is
clearly about AI, and every kept video needs at least one unambiguous hit. Lectures in a course playlist
inherit the course's topic, so terse NPTEL titles like "Lecture 1: Introduction" are still placed.
13 topics: AI fundamentals, math for ML, ML foundations, deep learning, NLP, LLMs & transformers,
RAG & vector search, AI agents, computer vision, generative models, reinforcement learning,
AI engineering & MLOps, and AI safety & governance.

**Level.** Known course numbers decide first (CS229 intermediate, CS336/CS25/CS234 advanced…), then
title and playlist wording ("what is", "introduction" vs "seminar", "theory", "from scratch"), length,
and a mild channel default (IBM explainers lean beginner, university lectures intermediate).

**Format.** Lecture, Explainer, Tutorial, Talk, Deep dive, or News & Podcast (kept out of learning paths).

**Quality score (0–100).** Weights are in `config/taxonomy.toml` under `[ranking]`:

| component    | weight | signal |
|--------------|-------:|--------|
| approval     | 0.30 | likes per view, Bayesian-smoothed, percentile within channel |
| popularity   | 0.25 | total views and views/day, percentile within channel |
| engagement   | 0.10 | comments per view, smoothed |
| freshness    | 0.15 | half-life per topic (agents 1.5 y … math 15 y) |
| completeness | 0.10 | captions, chapters, a real description |
| structure    | 0.10 | part of a full course |

…multiplied by the channel `weight`, plus any curator `boost`. Comparing within a channel keeps a huge
channel from burying a smaller one. These are proxies for quality, not a review of the teaching, which
is why every video page shows its score breakdown and tagging reasons, and why `overrides.toml` lets
you boost, pin, retag or hide anything.

**Learning paths.** For each topic and level, up to 8 steps are picked by score (with a bonus for the
topic being the item's primary topic, light channel diversity, and at most half of the steps being
courses). Courses are taken whole: a lecture from the middle of a course never appears as a standalone
step. Beginner levels lead with short explainers; intermediate and advanced lead with full courses.
Three roadmaps chain topics into tracks: *Core AI for CS majors*, *Building AI agents*, and
*Computer vision & generative media* (edit them in `taxonomy.toml`).

## Curate

`config/overrides.toml`:

```toml
exclude_videos = ["VIDEO_ID"]
include_videos = ["VIDEO_ID"]          # force-include a video from a configured channel
[boost]
"VIDEO_ID" = 10
[[retag]]
video = "VIDEO_ID"
level = "beginner"
[[pin]]
topic = "ai-agents"
level = "beginner"
video = "VIDEO_ID"
```

## Safety nets

- The build fails (and the previous site stays live) if the config is invalid, the API key is
  rejected, tests fail, or the catalog comes out empty.
- Quota exhaustion is not a failure: the site is rebuilt from what's cached and the scan resumes.
- The page has a strict Content-Security-Policy; video titles are always HTML-escaped; embeds use
  `youtube-nocookie.com` and only load when you press play.
