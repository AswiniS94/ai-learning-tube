"""Generates tests/fixtures/sample.json: a small, API-shaped sample dataset.

Titles imitate the style of each channel. IDs are fake ("smp" + digits), so
thumbnails/embeds won't load in the demo build — that's expected.
Includes deliberate traps: electrical transformers, chemical diffusion,
promo videos, Shorts, a private video, and a foreign-channel video inside a
playlist.
"""

import json
from pathlib import Path

STAN = "UCBa5G_ESCn8Yd4vw5U-gIcg"
IBM = "UCKWaEZ-_VweaEx1j62do_vQ"
NPTEL = "UCnptelFixtureChannel01x"
OTHER = "UCsomeOtherChannel000001"

_n = 0
videos, playlists = [], []


def vid(channel, title, dur, views, likes, comments, published, desc="", tags=(), caption=True, **extra):
    global _n
    _n += 1
    v = {"id": f"smp{_n:08d}", "channel": channel, "title": title, "duration": dur, "views": views,
         "likes": likes, "comments": comments, "published": published + "T15:00:00Z",
         "description": desc, "tags": list(tags), "caption": caption, **extra}
    videos.append(v)
    return v["id"]


def pl(channel, pid, title, items, desc=""):
    playlists.append({"id": pid, "channel": channel, "title": title, "items": items, "description": desc})


STAN_BP = ("\n\nStanford Online is the portal for academic and professional education at Stanford."
           "\nFor more information about Stanford's Artificial Intelligence programs visit: https://stanford.io/ai")
IBM_BP = ("\n\nAI news moves fast. Sign up for a monthly newsletter for AI updates from IBM → https://ibm.biz/news"
          "\nWant to learn more about AI agents? → https://ibm.biz/agents"
          "\nSubscribe to build your skillset and gain insights from IBM experts.")
NPTEL_BP = "\n\nCOPYRIGHT reserved to NPTEL, Govt. of India. Duplication prohibited."

# ---------------- Stanford Online
cs229 = [vid(STAN, f"Stanford CS229: Machine Learning Course, Lecture {i} - Andrew Ng (Autumn 2018)" + s, 4500 + i * 60,
             v, l, c, "2020-04-17", "Andrew Ng, Adjunct Professor of Computer Science." + STAN_BP)
         for i, s, v, l, c in [
             (1, "", 4_800_000, 72_000, 1_500), (2, " | Linear Regression and Gradient Descent", 2_100_000, 30_000, 900),
             (3, " | Locally Weighted & Logistic Regression", 1_100_000, 15_000, 400),
             (4, " | Perceptron & Generalized Linear Model", 700_000, 9_000, 250),
             (5, " | GDA & Naive Bayes", 520_000, 7_000, 180), (6, " | Support Vector Machines", 480_000, 6_800, 150)]]
pl(STAN, "PLstanCS229", "Stanford CS229: Machine Learning Full Course taught by Andrew Ng | Autumn 2018", cs229)

cs336 = [vid(STAN, f"Stanford CS336 Language Modeling from Scratch | Spring 2025 | Lecture {i}: {t}", 4700, v, l, c,
             "2025-04-10", "Percy Liang and Tatsunori Hashimoto." + STAN_BP)
         for i, t, v, l, c in [(1, "Overview and Tokenization", 900_000, 22_000, 700),
                               (2, "PyTorch, Resource Accounting", 300_000, 6_000, 120),
                               (3, "Architectures, Hyperparameters", 210_000, 4_900, 90),
                               (4, "Mixture of Experts", 180_000, 4_100, 80)]]
pl(STAN, "PLstanCS336", "Stanford CS336 Language Modeling from Scratch | Spring 2025", cs336)

cs231 = [vid(STAN, f"Stanford CS231N | Spring 2025 | Lecture {i}: {t}", 4400, v, l, c, "2025-05-20",
             "Fei-Fei Li, Ehsan Adeli, Justin Johnson." + STAN_BP)
         for i, t, v, l, c in [(1, "Introduction", 400_000, 8_000, 200),
                               (2, "Image Classification with Linear Classifiers", 150_000, 3_000, 60),
                               (5, "Image Classification with CNNs", 120_000, 2_600, 50),
                               (9, "Object Detection, Image Segmentation, Visualizing and Understanding", 90_000, 2_100, 40)]]
pl(STAN, "PLstanCS231n", "Stanford CS231N Deep Learning for Computer Vision | Spring 2025", cs231)

vid(STAN, "Stanford Seminar - Building Reliable AI Agents in the Real World", 3600, 60_000, 1_400, 60, "2025-11-03",
    "In this talk we discuss evaluation and failure modes of LLM agents." + STAN_BP)
vid(STAN, "What Is Unsupervised Learning in Machine Learning?", 260, 25_000, 700, 15, "2025-09-01", STAN_BP.strip())
vid(STAN, "How Does K-means Clustering Work?", 300, 31_000, 820, 20, "2025-09-08", STAN_BP.strip())
vid(STAN, "Stanford Online AI Programs Top Questions: When and How to Enroll in Online AI Courses", 900, 9_000, 100, 5,
    "2025-08-28", "Learn about AI programs." + STAN_BP)
vid(STAN, "Stanford CS109 I Central Limit Theorem I 2022 I Lecture 18", 4800, 40_000, 600, 20, "2022-10-01",
    "Chris Piech." + STAN_BP)
vid(STAN, "Stanford Robotics Seminar ENGR319 | Autumn 2025 | Adaptive Robots", 3500, 5_000, 120, 4, "2025-10-20", STAN_BP.strip())
vid(STAN, "Stanford Webinar - Large Language Models Get the Hype, but Compound Systems Are the Future of AI",
    3300, 110_000, 2_500, 120, "2024-06-12", "Matei Zaharia on compound AI systems." + STAN_BP)
vid(STAN, "AI in 60 seconds #shorts", 45, 300_000, 9_000, 40, "2025-07-01", STAN_BP.strip())

# ---------------- IBM Technology
agents = [
    vid(IBM, "What are AI Agents?", 740, 1_900_000, 42_000, 900, "2024-07-15",
        "AI agents use large language models to reason, plan and call tools." + IBM_BP, ["ai agents", "llm"]),
    vid(IBM, "AI Agents vs Agentic AI: What's the Difference?", 610, 400_000, 11_000, 300, "2025-06-01",
        "Martin Keen compares single agents with agentic systems." + IBM_BP),
    vid(IBM, "What is MCP? Model Context Protocol Explained", 540, 650_000, 17_000, 500, "2025-03-20",
        "How the Model Context Protocol connects AI agents to tools and data." + IBM_BP),
    vid(IBM, "Build an AI Agent with LangGraph: Step by Step Tutorial", 1500, 120_000, 3_900, 210, "2025-08-02",
        "Hands-on: build a tool-calling agent with LangGraph and Python." + IBM_BP, ["langgraph", "python"]),
]
pl(IBM, "PLibmAgents", "AI Agents", agents)
vid(IBM, "What is Retrieval-Augmented Generation (RAG)?", 380, 1_300_000, 30_000, 600, "2023-08-22",
    "Marina Danilevsky explains RAG." + IBM_BP, ["rag", "llm"])
vid(IBM, "RAG vs Fine-Tuning", 500, 300_000, 8_000, 250, "2024-11-10", "When to retrieve and when to fine tune an LLM." + IBM_BP)
vid(IBM, "LangChain vs LangGraph: A Tale of Two Frameworks", 600, 350_000, 9_500, 280, "2024-09-30", IBM_BP.strip())
vid(IBM, "How Transformers Work: Attention Explained", 620, 500_000, 14_000, 330, "2024-02-14",
    "Self-attention and the transformer architecture behind LLMs." + IBM_BP)
vid(IBM, "What is a Vector Database?", 480, 420_000, 10_000, 200, "2024-04-02", IBM_BP.strip())
vid(IBM, "What is LLM Quantization?", 560, 90_000, 2_800, 90, "2025-01-15", "Shrinking LLMs for inference." + IBM_BP)
vid(IBM, "Explainable AI Explained", 450, 70_000, 1_500, 40, "2023-05-05", IBM_BP.strip())
vid(IBM, "What is Prompt Injection?", 590, 160_000, None, 120, "2024-12-01", "Attacks on LLM apps." + IBM_BP)
vid(IBM, "What are Generative Adversarial Networks (GANs)?", 520, 300_000, 7_000, None, "2022-03-10", IBM_BP.strip())
vid(IBM, "Kubernetes Explained", 600, 2_000_000, 40_000, 800, "2021-01-01",
    "Learn how Kubernetes orchestrates containers for AI workloads." + IBM_BP)
vid(IBM, "Container Orchestration Explained", 540, 400_000, 9_000, 200, "2021-05-01", "AI-ready infrastructure." + IBM_BP)
vid(IBM, "What is Quantum Computing?", 700, 900_000, 20_000, 500, "2023-01-01", IBM_BP.strip())
moe = [vid(IBM, f"GPT-5 drops, agent wars and open models | Mixture of Experts {n}", 2700, 40_000, 900, 60, f"2025-0{n}-05",
           "In this episode of Mixture of Experts, Tim Hwang and panelists discuss the week in AI." + IBM_BP)
       for n in (4, 5, 6)]
pl(IBM, "PLibmMoE", "Mixture of Experts", moe)

# ---------------- NPTEL
other = vid(OTHER, "Deep Learning Lecture 3 (mirror)", 3000, 1000, 10, 1, "2021-01-01", "mirror")
dl = [vid(NPTEL, f"Lecture {i}: {t}", 2400 + i * 30, v, l, c, "2019-01-10", "Prof. Mitesh M. Khapra, IIT Madras." + NPTEL_BP)
      for i, t, v, l, c in [(1, "Introduction", 300_000, 4_000, 120), (2, "McCulloch Pitts Neuron, Thresholding Logic", 150_000, 2_000, 50),
                            (3, "Perceptron Learning Algorithm", 120_000, 1_700, 40), (4, "Gradient Descent", 100_000, 1_500, 30),
                            (5, "Backpropagation", 90_000, 1_400, 30)]]
priv = vid(NPTEL, "Lecture 6: Hidden", 2500, 0, 0, 0, "2019-01-10", private=True)
pl(NPTEL, "PLnptelDL", "Deep Learning - IIT Madras", dl[:2] + [other] + dl[2:] + [priv])

ml = [vid(NPTEL, f"{code} - {t}", 1800, v, l, c, "2021-07-01", "Prof. Balaraman Ravindran." + NPTEL_BP)
      for code, t, v, l, c in [("mod01lec01", "Introduction to Machine Learning", 220_000, 3_000, 80),
                               ("mod02lec03", "Linear Regression", 90_000, 1_100, 25),
                               ("mod03lec05", "Support Vector Machines", 70_000, 900, 20),
                               ("mod04lec02", "Decision Trees", 60_000, 800, 15)]]
pl(NPTEL, "PLnptelML", "Introduction to Machine Learning - IIT Madras", ml)

nlp = [vid(NPTEL, f"Natural Language Processing - Lecture {i}: {t}", 2000, v, l, c, "2018-09-01",
           "Prof. Pawan Goyal, IIT Kharagpur." + NPTEL_BP)
       for i, t, v, l, c in [(1, "Introduction", 80_000, 900, 30), (2, "Text Processing and Tokenization", 40_000, 500, 10),
                             (3, "Language Modeling: N-grams", 35_000, 450, 8)]]
pl(NPTEL, "PLnptelNLP", "Natural Language Processing - IIT Kharagpur", nlp)

em = [vid(NPTEL, f"Lecture {i}: {t}", 2600, 30_000, 300, 10, "2017-02-01", "Prof. Kumar, IIT Delhi." + NPTEL_BP)
      for i, t in [(1, "Single Phase Transformer Basics"), (2, "Transformer Equivalent Circuit"), (3, "Power Transformer Protection"),
                   (4, "Attention to Losses and Efficiency")]]
pl(NPTEL, "PLnptelEM", "Electrical Machines - I", em)
mt = [vid(NPTEL, f"Lecture {i}: {t}", 2500, 20_000, 200, 5, "2016-02-01", "Prof. Rao, IIT Kharagpur." + NPTEL_BP)
      for i, t in [(7, "Diffusion in Gases"), (8, "Diffusion Coefficient Estimation"), (9, "Agents for Mass Transfer")]]
pl(NPTEL, "PLnptelMT", "Mass Transfer Operations", mt)
vid(NPTEL, "Linear Algebra - Lecture 12: Eigenvalues and Eigenvectors", 2700, 50_000, 600, 12, "2015-01-01", NPTEL_BP.strip())

data = {
    "channels": [
        {"id": STAN, "handle": "@stanfordonline", "title": "Stanford Online", "subs": 1_200_000},
        {"id": IBM, "handle": "@IBMTechnology", "title": "IBM Technology", "subs": 1_400_000},
        {"id": NPTEL, "handle": "@nptel-indianinstituteofsci8064", "title": "NPTEL", "subs": 4_000_000},
    ],
    "videos": videos,
    "playlists": playlists,
}
out = Path(__file__).parent / "fixtures" / "sample.json"
out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out}: {len(videos)} videos, {len(playlists)} playlists")
