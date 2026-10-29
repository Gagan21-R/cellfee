"""Central configuration: paths, environment, and documented decision constants."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional
    load_dotenv = None

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_CSV = DATA_DIR / "processed" / "severson_snapshots.csv"
ARTIFACTS = ROOT / "artifacts"
EVIDENCE_DIR = ARTIFACTS / "evidence"
RESULTS_JSON = ARTIFACTS / "results.json"
MARKET_JSON = ARTIFACTS / "market.json"

if load_dotenv is not None:
    load_dotenv(ROOT / ".env")

# --- Sponsor credentials (never hard-code; read from .env) -------------------
QCLOUD_API_KEY = os.getenv("QPIAI_QCLOUD_API_KEY", "").strip()
OPT_API_KEY = os.getenv("QPIAI_OPT_API_KEY", "").strip()

# Device for shot-based kernel evidence circuits. QpiAI-QSV-Local needs no key.
# With a QCloud key, set e.g. QpiAI-QSV-Simulator, QpiAI-QDM-Simulator or QpiAI-Indus-1.
KERNEL_DEVICE = os.getenv("CELLFEE_KERNEL_DEVICE", "QpiAI-QSV-Local")
KERNEL_SHOTS = int(os.getenv("CELLFEE_KERNEL_SHOTS", "2000"))
# Max number of battery pairs sent as shot-based fidelity circuits (credit guard).
KERNEL_EVIDENCE_PAIRS = int(os.getenv("CELLFEE_KERNEL_EVIDENCE_PAIRS", "60"))
# Device for QAOA when it runs through QpiAI Opt on the QCloud platform.
QAOA_DEVICE = os.getenv("CELLFEE_QAOA_DEVICE", "QpiAI-QSV-Local")
# QCloud experiment that cloud jobs are filed under; create it once in the QCloud web UI.
QCLOUD_EXPERIMENT = os.getenv("CELLFEE_QCLOUD_EXPERIMENT", "cellfee")

SEED = 7

# --- Battery & decision constants (versioned, documented in docs/DECISION_RULES.md)
RULES_VERSION = "2.0.0"
NOMINAL_CAPACITY_AH = 1.1          # A123 APR18650M1A LFP cells (Severson et al. 2019), rated 1.1 Ah
NOMINAL_VOLTAGE_V = 3.3
LONG_LIFE_CYCLES = 300             # "fit for second life": >= this many cycles left before 80% capacity
FIRST_LIFE_EOL_SOH = 0.80          # the dataset's end-of-life definition (80% of rating)
P_REUSE_MIN = 0.50                 # combined P(fit) below this never counts as a reuse candidate
GRADE_A_P = 0.85                   # grade A: both models agree, combined P(fit) >= this
GRADE_B_P = 0.65                   # grade B: both models agree, combined P(fit) >= this
GRADE_C_P = 0.25                   # grade C (recycle route): combined P(fit) <= this

# --- AQSVC (annealing-based quantum support vector classifier)
AQSVC_BAG = int(os.getenv("CELLFEE_AQSVC_BAG", "25"))       # bagging members per feature map
AQSVC_BOOST = int(os.getenv("CELLFEE_AQSVC_BOOST", "25"))   # boosting members per feature map
AQSVC_MAPS = (8, 7)                # heterogeneous models: one tuned feature map on 8 inputs, one on the 7 features
AQSVC_MEMBERS = (AQSVC_BAG + AQSVC_BOOST) * len(AQSVC_MAPS)  # QUBO-trained SVMs in one AQSVC model
AQSVC_STACK_C = 0.5                # inverse L2 strength of the stacking meta-learner
AQSVC_WORKERS = int(os.getenv("CELLFEE_AQSVC_WORKERS", "5"))  # QUBOs solved in parallel processes
AQSVC_SUBSET = 40                  # training batteries per member (20 fit + 20 not fit)
AQSVC_BITS = 2                     # binary bits per support-vector weight alpha (alpha in 0..3)
AQSVC_BASE = 2
AQSVC_XI = 1.0                     # QUBO penalty weight for sum(alpha*y) = 0
AQSVC_READS = 4                    # QpiAI Opt local annealer reads per member (free-tier budget)
KTA_TRAIN_SAMPLES = 240            # snapshots used to train the feature map (kernel-target alignment)

# Economics used by the allocation objective (illustrative, stated as assumptions)
CURRENCY = "INR"                   # all money below is in Indian rupees (₹)
VALUE_PER_KWH_SECOND_LIFE = 8300.0 # ₹/kWh of usable second-life energy (~₹30 per full 1.1 Ah LFP cell)
RECYCLE_VALUE_PER_CELL = 4.15      # ₹ material recovery net of processing (LFP has little valuable metal)
TEST_COST_PER_CELL = 6.64          # ₹ full capacity test on a multi-channel cycler
FAILURE_COST_PER_CELL = 49.8       # ₹ pack rework if a reused cell turns out to have too little life left
PACK_SIZE = 4                      # cells per second-life module in this demo
FLEET_SIZE = int(os.getenv("CELLFEE_FLEET_SIZE", "5000"))   # battery records screened and decided
BATCH_SIZE = 33                    # batteries per truckload; each batch is one QpiAI Opt problem
MAX_PACKS_PER_BATCH = 3            # a batch of 33 rarely fills more; each extra pack slows the exact MILP ~2x
MISMATCH_WEIGHT = 12.45            # lambda: ₹ per unit of in-pack pair dissimilarity
KERNEL_FORBID_BELOW = 0.15         # pairs with quantum similarity below this never share a pack
SOH_SPREAD_FORBID = 0.05           # pairs whose health differs by more than this never share a pack
