from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPO_ROOT / "projects"
WORKSPACE_ROOT = REPO_ROOT.parent

DEFAULT_JSON_PATH = "/data/lizhe/Medteam_projects/kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json"
DEFAULT_TEMPLATE_DIR = str(PROJECT_ROOT / "templates/l0_l5")
DEFAULT_PROMPT_DIR = str(PROJECT_ROOT / "outputs/prompts")
DEFAULT_FILTERED_CSV = "/data/fangyuxuan/projects/medical_dl/SurvPGC/patients_index/filtered_patient_id.csv"
DEFAULT_CKPT = str(WORKSPACE_ROOT / "CONCH/pytorch_model.bin")
DEFAULT_OUT_DIR = str(PROJECT_ROOT / "outputs/embeddings")
DEFAULT_GPU = "7"
