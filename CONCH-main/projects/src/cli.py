import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import clinical_pipeline as base  # noqa: E402

from .config import (  # noqa: E402
    DEFAULT_CKPT,
    DEFAULT_FILTERED_CSV,
    DEFAULT_GPU,
    DEFAULT_JSON_PATH,
    DEFAULT_OUT_DIR,
    DEFAULT_PROMPT_DIR,
    DEFAULT_TEMPLATE_DIR,
)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scheme", default="all", help="scheme name, or all")
    parser.add_argument("--json_path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--template_dir", default=DEFAULT_TEMPLATE_DIR)
    parser.add_argument("--prompt_dir", default=DEFAULT_PROMPT_DIR)
    parser.add_argument("--filtered_csv", default=DEFAULT_FILTERED_CSV)
    parser.add_argument("--ckpt", default=DEFAULT_CKPT)
    parser.add_argument("--out", default=DEFAULT_OUT_DIR)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--gpu", default=DEFAULT_GPU)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clinical Pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("json2prompt", help="JSON -> prompt CSV")
    _add_common_args(p1)

    p2 = sub.add_parser("encode", help="prompt CSV -> embeddings")
    _add_common_args(p2)

    p3 = sub.add_parser("pipeline", help="json2prompt + encode")
    _add_common_args(p3)

    args = parser.parse_args()

    base.SCHEME_TEMPLATE.clear()
    base.SCHEME_PROMPT_FILE.clear()
    base.SCHEME_DIRNAME.clear()
    base.SCHEME_COLS.clear()
    base.SCHEME_CONFIG.clear()
    base.load_custom_schemes(args.template_dir)

    known_schemes = set(base.SCHEME_CONFIG.keys())
    if args.scheme != "all" and args.scheme not in known_schemes:
        parser.error(f"unknown scheme: {args.scheme}; available: {sorted(known_schemes)}")

    schemes = list(base.SCHEME_CONFIG.keys()) if args.scheme == "all" else [args.scheme]
    base.DEFAULT_GPU = args.gpu

    if args.cmd in ("json2prompt", "pipeline"):
        for scheme in schemes:
            base.run_json2prompt(
                json_path=args.json_path,
                scheme=scheme,
                template_dir=args.template_dir,
                prompt_dir=args.prompt_dir,
            )

    if args.cmd in ("encode", "pipeline"):
        for scheme in schemes:
            base.run_encode(
                scheme=scheme,
                prompt_dir=args.prompt_dir,
                filtered_csv=args.filtered_csv,
                ckpt=args.ckpt,
                out_dir=args.out,
                batch_size=args.batch_size,
            )

