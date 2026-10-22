"""Command line: python3 -m rewind {build,synth,demo} ...

build  Analyse a Spotify extended streaming history export and write a static story site.
synth  Write a synthetic export with planted ground truth (no personal data).
demo   synth + build + score the result against the planted truth.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from datetime import date
from pathlib import Path

from . import config, evaluate, pipeline, synth

SITE_FILES = ("index.html", "styles.css")


def site_shell_dir() -> Path:
    """The player files: web/ in a source checkout, or the installed rewind_site package."""
    web = config.ROOT / "web"
    if (web / "index.html").exists():
        return web
    import rewind_site  # installed package data (a namespace package, so use its __path__)
    return Path(next(iter(rewind_site.__path__)))


def copy_site_shell(site_dir: Path) -> None:
    """Copy the player (HTML, CSS, JS) next to the generated site/data."""
    web = site_shell_dir()
    site_dir.mkdir(parents=True, exist_ok=True)
    for name in SITE_FILES:
        shutil.copy2(web / name, site_dir / name)
    shutil.copytree(web / "js", site_dir / "js", dirs_exist_ok=True)


def parse_tz(items: list[str]) -> dict:
    out = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"--tz expects COUNTRY=Zone, got {item!r}")
        country, zone = item.split("=", 1)
        out[country.strip().upper()] = zone.strip()
    return out


def build(export: Path, out: Path | None, techlog: Path | None, tz: dict, quick: bool) -> dict:
    reps = (10, 60) if quick else (30, 200)
    if out is None:  # this project's own layout: work/, outputs/, web/ is the site
        paths = config.Paths(export_dir=export, techlog_dir=techlog or config.TECH_LOG_DIR)
    else:
        paths = config.Paths.under(out, export, techlog)
    t0 = time.perf_counter()
    result = pipeline.run(*reps, paths=paths, tz_overrides=tz)
    if out is not None:
        copy_site_shell(Path(out) / "site")  # only after a successful analysis
    o = result["metrics"]["overall"]
    print(f"analysed {result['audit']['raw_records']:,} records in {time.perf_counter() - t0:.1f} s: "
          f"{o['minutes']:,.0f} music minutes, {len(result['era_validation']['eras'])} eras, "
          f"{len(result['stories']['chapters'])} chapters")
    print(f"site: {(Path(out) / 'site') if out else config.ROOT / 'web'}")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m rewind", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="analyse an export and write the story site")
    b.add_argument("--export", type=Path, default=config.EXPORT_DIR, help="folder with Streaming_History_*.json")
    b.add_argument("--techlog", type=Path, default=None, help="optional technical-log folder (cross-check only)")
    b.add_argument("--out", type=Path, default=None, help="write a self-contained build here (default: this project)")
    b.add_argument("--tz", action="append", metavar="COUNTRY=Zone", help="timezone override, e.g. US=America/Chicago")
    b.add_argument("--quick", action="store_true", help="fewer validation resamples (faster, for trying it out)")
    s = sub.add_parser("synth", help="write a synthetic export with planted ground truth")
    s.add_argument("--out", type=Path, required=True, help="folder for the export files")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--months", type=int, default=40)
    d = sub.add_parser("demo", help="synthetic export -> build -> ground-truth evaluation")
    d.add_argument("--out", type=Path, default=config.ROOT / "dist" / "demo")
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--quick", action="store_true")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except (FileExistsError, FileNotFoundError) as err:
        print(f"rewind: {err}", file=sys.stderr)
        return 2


def run(args: argparse.Namespace) -> int:

    if args.cmd == "build":
        build(args.export, args.out, args.techlog, parse_tz(args.tz), args.quick)
        return 0
    if args.cmd == "synth":
        truth = synth.generate(args.out, seed=args.seed, months=args.months)
        print(f"wrote {truth['raw_records']:,} records to {args.out}; truth in {Path(args.out).parent / 'ground_truth.json'}")
        return 0
    if args.cmd == "demo":
        out = Path(args.out)
        truth = synth.generate(out / "export", seed=args.seed, start=date(2022, 3, 1))
        result = build(out / "export", out, None, {}, args.quick)
        report = evaluate.evaluate(result, truth)
        evaluate.write(report, out / "outputs")
        print(f"ground truth: {report['passed']}/{report['total']} checks pass "
              f"(era boundaries precision {report['boundaries']['precision']}, recall {report['boundaries']['recall']})")
        for c in report["checks"]:
            if not c["pass"]:
                print(f"  FAIL {c['check']}: planted {c['expected']}, recovered {c['actual']}")
        return 0 if report["passed"] == report["total"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
