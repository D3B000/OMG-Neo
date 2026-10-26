"""Minimal standalone injection host. Never imports the stdio service entry."""
import argparse
import multiprocessing
from pathlib import Path
import sys
import traceback


def main():
    # ProcessWaiter uses multiprocessing in this executable, too.
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description='Neo isolated injection host')
    parser.add_argument('--injector', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--lite-src', type=Path)
    parser.add_argument('--request-file', type=Path, required=True)
    parser.add_argument('--result-file', type=Path, required=True)
    args = parser.parse_args()
    if not getattr(sys, 'frozen', False):
        args.lite_src = args.lite_src or Path(__file__).resolve().parents[1] / 'OMGLite/src'
    try:
        from injection_entry import run_injector
        return run_injector(args)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
