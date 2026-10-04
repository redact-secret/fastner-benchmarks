import argparse
import sys

from .policy import load_policy


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fnbench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("policy-check", help="validate the qualification policy")
    sub.add_parser("populations-check", help="validate the population registry")
    sub.add_parser("pins-check", help="validate candidate/reference pins")
    for name, mod in COMMANDS.items():
        sub.add_parser(name, help=mod[0])
    args, rest = ap.parse_known_args(argv)
    if args.cmd == "policy-check":
        p = load_policy()
        print(f"policy {p['policy_version']} ok: {len(p['dimensions'])} dimensions, no_single_score={p['no_single_score']}")
        return 0
    if args.cmd == "populations-check":
        from .populations import load_populations
        r = load_populations()
        for p in r["populations"]:
            print(f"{p['id']:22} {p['role']:20} {p['status']}")
        return 0
    if args.cmd == "pins-check":
        from .pins import load_candidates, pin_table
        cfg = load_candidates()
        for r in pin_table(cfg):
            print(f"{r['id']:26} {r['role']:10} {r['pin_status']:11} missing={len(r['missing'])}")
        return 0
    return COMMANDS[args.cmd][1](rest)


def _lazy(mod, fn="main"):
    def run(rest):
        import importlib
        return getattr(importlib.import_module(f"fnbench.{mod}"), fn)(rest)
    return run


COMMANDS = {
    "report": ("generate the bakeoff report from artifacts", _lazy("report")),
}


if __name__ == "__main__":
    sys.exit(main())
