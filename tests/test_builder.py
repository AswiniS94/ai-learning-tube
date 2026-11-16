import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from builder.__main__ import main, run_sync, tag_catalog
from builder.classify import Classifier
from builder.config import ConfigError, load_config
from builder.fake import FakeYouTube
from builder.rank import percentiles
from builder.state import empty_state, load_state, save_state
from builder.sync import Log
from builder.textutil import KeywordMatcher, boilerplate_lines, clean_description, normalize, parse_duration

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "sample.json"
CFG = load_config(ROOT / "config")


def by_title(catalog):
    return {v["t"]: v for v in catalog["videos"]}


class TextUtilTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("Fine-Tuning LLMs: Résumé!"), "fine tuning llms resume")
        self.assertEqual(normalize("Stanford CS 229 & CS231n"), "stanford cs229 cs231n")

    def test_matcher_whole_words_and_longest(self):
        m = KeywordMatcher(["rag", "reinforcement learning", "reinforcement learning from human feedback"])
        self.assertEqual(m.find(normalize("Storage and leverage")), set())
        self.assertEqual(m.find(normalize("What is RAG?")), {"rag"})
        self.assertEqual(m.find(normalize("Reinforcement learning from human feedback")),
                         {"reinforcement learning from human feedback"})

    def test_parse_duration(self):
        self.assertEqual(parse_duration("PT1H2M3S"), 3723)
        self.assertEqual(parse_duration("PT45S"), 45)
        self.assertEqual(parse_duration("P1DT1H"), 90000)
        self.assertEqual(parse_duration("P0D"), 0)
        self.assertEqual(parse_duration(None), 0)
        self.assertEqual(parse_duration("garbage"), 0)

    def test_boilerplate_and_links_removed(self):
        descs = ["Topic %d\nSubscribe for more AI news" % i for i in range(10)]
        bp = boilerplate_lines(descs)
        self.assertIn("subscribe for more ai news", bp)
        cleaned = clean_description("Real content about RAG\nSubscribe for more AI news\nLearn agents → https://x.io/a", bp)
        self.assertEqual(cleaned, "real content about rag")


class ClassifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clf = Classifier(CFG)

    def tag(self, title, desc="", ch="ibm-technology", duration=600, playlists=()):
        v = {"title": title, "desc": desc, "ch": ch, "details": {"duration": duration, "tags": []}}
        return self.clf.classify_video(v, set(), list(playlists))

    def test_ai_videos(self):
        self.assertEqual(self.tag("What are AI Agents?")["topics"][0], "ai-agents")
        self.assertEqual(self.tag("What is Retrieval-Augmented Generation (RAG)?")["topics"][0], "rag")
        r = self.tag("How Transformers Work: Attention Explained", "Self-attention behind LLMs")
        self.assertEqual(r["topics"][0], "llms")
        self.assertEqual(r["level"], "beginner")
        self.assertEqual(self.tag("Object Detection with YOLO")["topics"][0], "computer-vision")
        self.assertEqual(self.tag("Diffusion Models Explained", "generative AI for images")["topics"][0], "generative-models")

    def test_ambiguous_words_need_ai_context(self):
        for title in ["Lecture 1: Single Phase Transformer Basics", "Lecture 7: Diffusion in Gases",
                      "Agents for Mass Transfer", "Linear Algebra - Lecture 12: Eigenvalues"]:
            self.assertFalse(self.tag(title, ch="nptel")["relevant"], title)

    def test_generic_it_videos_excluded_even_with_ai_mentions(self):
        self.assertFalse(self.tag("Kubernetes Explained", "Kubernetes for AI workloads")["relevant"])
        self.assertFalse(self.tag("Container Orchestration Explained", "AI-ready infrastructure")["relevant"])

    def test_promos_excluded(self):
        self.assertFalse(self.tag("Stanford Online AI Programs Top Questions: When and How to Enroll in Online AI Courses",
                                  ch="stanford-online")["relevant"])

    def test_course_levels_and_formats(self):
        r = self.tag("Stanford CS336 Language Modeling from Scratch | Lecture 3: Architectures", ch="stanford-online", duration=4700)
        self.assertEqual((r["level"], r["format"]), ("advanced", "Lecture"))
        r = self.tag("Stanford CS229: Machine Learning Course, Lecture 2", ch="stanford-online", duration=4700)
        self.assertEqual((r["topics"][0], r["level"]), ("ml-foundations", "intermediate"))
        self.assertEqual(self.tag("Stanford Seminar - Building Reliable AI Agents", ch="stanford-online", duration=3600)["format"], "Talk")
        self.assertEqual(self.tag("Build an AI Agent with LangGraph: Step by Step Tutorial", duration=1500)["format"], "Tutorial")

    def test_course_playlist_inheritance(self):
        pl = self.clf.classify_playlist({"title": "Deep Learning - IIT Madras", "desc": ""}, set())
        pl["course"] = True
        r = self.tag("Lecture 1: Introduction", ch="nptel", duration=2400, playlists=[pl])
        self.assertTrue(r["relevant"])
        self.assertEqual(r["topics"][0], "deep-learning")
        self.assertFalse(self.tag("Lecture 1: Introduction", ch="nptel", duration=2400)["relevant"])


class RankTests(unittest.TestCase):
    def test_percentiles(self):
        self.assertEqual(percentiles({}), {})
        self.assertEqual(percentiles({"a": 5}), {"a": 0.5})
        p = percentiles({"a": 1, "b": 2, "c": 2, "d": 3})
        self.assertEqual(p["a"], 0.0)
        self.assertEqual(p["d"], 1.0)
        self.assertAlmostEqual(p["b"], p["c"])


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, *extra):
        rc = main(["build", "--fixture", str(FIXTURE), "--state", str(self.tmp / "state"),
                   "--out", str(self.tmp / "dist"), "--quiet", *extra])
        self.assertEqual(rc, 0)
        return json.loads((self.tmp / "dist" / "data" / "catalog.json").read_text(encoding="utf-8"))

    def test_full_build(self):
        cat = self.build()
        titles = by_title(cat)
        # included
        for t in ["What are AI Agents?", "Lecture 1: Introduction", "mod02lec03 - Linear Regression",
                  "Stanford CS229: Machine Learning Course, Lecture 1 - Andrew Ng (Autumn 2018)"]:
            self.assertIn(t, titles)
        # excluded: off-topic, promo, short, private, other channel
        for t in ["Kubernetes Explained", "Lecture 1: Single Phase Transformer Basics", "Lecture 7: Diffusion in Gases",
                  "AI in 60 seconds #shorts", "Lecture 6: Hidden", "Deep Learning Lecture 3 (mirror)",
                  "Stanford CS109 I Central Limit Theorem I 2022 I Lecture 18", "What is Quantum Computing?",
                  "Stanford Online AI Programs Top Questions: When and How to Enroll in Online AI Courses"]:
            self.assertNotIn(t, titles)
        self.assertEqual(titles["GPT-5 drops, agent wars and open models | Mixture of Experts 4"]["f"], "News & Podcast")
        # every video is fully tagged and scored
        for v in cat["videos"]:
            self.assertTrue(v["tp"] and v["lv"] in cat["levels"] and v["f"] in cat["formats"])
            self.assertTrue(0 <= v["q"] <= 100)
            self.assertGreaterEqual(v["d"], CFG.build["min_duration_seconds"])
        # paths reference real items, cover every topic, never include news or mid-course lectures
        vids = {v["id"]: v for v in cat["videos"]}
        series = {s["id"]: s for s in cat["series"]}
        in_course = {m for s in cat["series"] if s["course"] for m in s["v"]}
        self.assertEqual(set(cat["paths"]), {t.id for t in CFG.topics})
        for tid, p in cat["paths"].items():
            for lv, items in p.items():
                self.assertLessEqual(len(items), CFG.build["path_items_per_level"])
                for it in items:
                    if it["k"] == "s":
                        self.assertIn(it["id"], series)
                        self.assertEqual(series[it["id"]]["lv"], lv)
                    else:
                        v = vids[it["id"]]
                        self.assertEqual(v["lv"], lv)
                        self.assertNotEqual(v["f"], "News & Podcast")
                        self.assertNotIn(it["id"], in_course)
        self.assertNotIn("PLibmMoE", series)  # podcast playlist is not a course
        self.assertEqual(series["PLstanCS336"]["lv"], "advanced")
        self.assertEqual(len(series["PLnptelDL"]["v"]), 5)  # private + foreign videos dropped
        html = (self.tmp / "dist" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("{{", html)

    def test_incremental_run_is_cheap(self):
        self.build()
        first = load_state(self.tmp / "state")
        fake = FakeYouTube(FIXTURE)
        state = copy.deepcopy(first)
        run_sync(fake, CFG, state, Classifier(CFG), Log(False), full=False)
        names = [c[0] for c in fake.calls]
        self.assertNotIn("videos", names)  # stats are fresh (< stats_refresh_hours)
        self.assertLessEqual(fake.used, 12)

    def test_quota_interruption_resumes(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fake = FakeYouTube(data, budget=8)
        fake.PAGE = 5
        state = empty_state()
        run_sync(fake, CFG, state, Classifier(CFG), Log(False), full=False)
        self.assertLessEqual(fake.used, 8)
        resumable = [c for c in state["channels"].values() if c.get("uploads_resume_token")]
        self.assertTrue(resumable, "an interrupted full scan must leave a resume token")
        save_state(state, self.tmp / "state")
        for _ in range(6):  # later nights finish the job
            fake2 = FakeYouTube(data, budget=10_000)
            fake2.PAGE = 5
            run_sync(fake2, CFG, state, Classifier(CFG), Log(False), full=False)
        self.assertFalse(any(c.get("uploads_resume_token") for c in state["channels"].values()))
        nptel = [v for v in state["videos"].values() if v["ch"] == "nptel"]
        self.assertGreaterEqual(len(nptel), 20)

    def test_upload_cap_backfilled_by_playlists(self):
        fake = FakeYouTube(FIXTURE, uploads_cap=3)
        state = empty_state()
        run_sync(fake, CFG, state, Classifier(CFG), Log(False), full=False)
        _, _, tagged = tag_catalog(CFG, state, Classifier(CFG))
        titles = {state["videos"][v]["title"] for v in tagged}
        self.assertIn("Lecture 5: Backpropagation", titles)  # older than the newest 3 uploads


class ConfigTests(unittest.TestCase):
    def write(self, channels, taxonomy=None):
        d = Path(tempfile.mkdtemp())
        (d / "channels.toml").write_text(channels, encoding="utf-8")
        (d / "taxonomy.toml").write_text(taxonomy or (ROOT / "config" / "taxonomy.toml").read_text(encoding="utf-8"), encoding="utf-8")
        return d

    def test_rejects_bad_channel(self):
        with self.assertRaises(ConfigError):
            load_config(self.write('[[channel]]\nkey="Bad Key"\nname="x"\nhandle="@x"\n'))
        with self.assertRaises(ConfigError):
            load_config(self.write('[[channel]]\nkey="a"\nname="x"\n'))
        with self.assertRaises(ConfigError):
            load_config(self.write('[[channel]]\nkey="a"\nname="x"\nhandle="@x"\n[[channel]]\nkey="a"\nname="y"\nhandle="@y"\n'))

    def test_new_channel_is_easy(self):
        cfg = load_config(self.write('[[channel]]\nkey="mit-ocw"\nname="MIT OpenCourseWare"\nhandle="@mitocw"\n'))
        self.assertEqual(cfg.enabled_channels[0].key, "mit-ocw")


if __name__ == "__main__":
    unittest.main()


class YouTubeClientTests(unittest.TestCase):
    """The real HTTP client, with urllib mocked out."""

    def _http_error(self, status, reason):
        import io
        import urllib.error
        body = json.dumps({"error": {"code": status, "message": f"{reason} message", "errors": [{"reason": reason}]}}).encode()
        return urllib.error.HTTPError("https://x", status, reason, {}, io.BytesIO(body))

    def test_request_shape_and_errors(self):
        from unittest import mock
        from urllib.parse import parse_qs, urlparse
        from builder import youtube

        seen = []

        class Resp:
            def __init__(self, payload): self.payload = payload
            def read(self): return json.dumps(self.payload).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def ok(req, timeout=0):
            seen.append(req.full_url)
            return Resp({"items": [{"id": "UCx"}]})

        c = youtube.YouTubeClient("KEY", budget=100)
        with mock.patch("urllib.request.urlopen", ok):
            self.assertEqual(c.channel(handle="nptelhrd")["id"], "UCx")
        q = parse_qs(urlparse(seen[0]).query)
        self.assertEqual(urlparse(seen[0]).path, "/youtube/v3/channels")
        self.assertEqual(q["forHandle"], ["@nptelhrd"])
        self.assertEqual(q["key"], ["KEY"])
        self.assertEqual(c.used, 1)

        def raise_(status, reason):
            def f(req, timeout=0):
                raise self._http_error(status, reason)
            return f

        with mock.patch("urllib.request.urlopen", raise_(403, "quotaExceeded")):
            with self.assertRaises(youtube.QuotaExhausted):
                c.videos(["a"])
        with mock.patch("urllib.request.urlopen", raise_(400, "keyInvalid")):
            with self.assertRaises(youtube.FatalAPIError):
                c.videos(["a"])
        with mock.patch("urllib.request.urlopen", raise_(404, "playlistNotFound")):
            with self.assertRaises(youtube.YouTubeError):
                c.playlist_items_page("PLx")
        with mock.patch("urllib.request.urlopen", raise_(403, "playlistItemsNotAccessible")):
            with self.assertRaises(youtube.YouTubeError):
                c.playlist_items_page("PLx")
        with mock.patch("time.sleep", lambda s: None), mock.patch("urllib.request.urlopen", raise_(503, "backendError")):
            with self.assertRaises(youtube.YouTubeError):
                c.videos(["a"])
        c2 = youtube.YouTubeClient("KEY", budget=2)
        with mock.patch("urllib.request.urlopen", ok):
            c2.videos(["a"]); c2.videos(["b"])
            with self.assertRaises(youtube.QuotaExhausted):
                c2.videos(["c"])
