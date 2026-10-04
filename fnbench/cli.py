import argparse
import sys

from .policy import load_policy


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fnbench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("policy-check", help="validate the qualification policy")
    for name, mod in COMMANDS.items():
        sub.add_parser(name, help=mod[0])
    args, rest = ap.parse_known_args(argv)
    if args.cmd == "policy-check":
        p = load_policy()
        print(f"policy {p['policy_version']} ok: {len(p['dimensions'])} dimensions, no_single_score={p['no_single_score']}")
        return 0
    return COMMANDS[args.cmd][1](rest)


COMMANDS = {}  # populated by later modules via register()


def register(name, helptext, fn):
    COMMANDS[name] = (helptext, fn)


if __name__ == "__main__":
    sys.exit(main())
