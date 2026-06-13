import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

LLM_BASE_URL = "http://localhost:8003/v1"
LLM_MODEL = "mlx-community/gemma-4-26B-A4B-it-qat-4bit"
ENV_NAME = "l2rpn_neurips_2020_track2_small"
GRID2OP_LOCAL_DIR = os.path.join(ROOT, "data_grid2op")
DEMO_CHRONIC_IDX = 0

MAX_ACTIONS_PER_SUB = 600
TOP_K_CANDIDATES = 5
TOP_K_LOADED_LINES = 5
MAX_LOOP_ITERATIONS = 12
MAX_APPLY_ATTEMPTS = 2
STABILITY_CHECK_STEPS = 20
MAX_TOOL_RESULT_CHARS = 2000

RUN_DIR = os.path.join(ROOT, "artifacts", "run")
RENDER_DIR = os.path.join(RUN_DIR, "renders")

# Random event injector: autonomous grid dynamics between operator turns.
INJECTOR_PERIOD_SEC = 30.0
INJECTOR_JITTER_SEC = 12.0
INJECTOR_SEED = None
