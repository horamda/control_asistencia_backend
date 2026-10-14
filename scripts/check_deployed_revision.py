"""Read-only post-deployment check; never authenticates or changes business data."""
import argparse
import json
import time
import urllib.request


def validate(payload, expected):
    if payload.get("status") != "ok":
        raise ValueError("Backend health check failed")
    if payload.get("revision") != expected:
        raise ValueError("Backend revision differs from the expected release")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Backend base URL")
    parser.add_argument("--expected-revision", required=True, help="Full deployed Git commit SHA")
    args = parser.parse_args()
    started = time.perf_counter()
    request = urllib.request.Request(args.url.rstrip("/") + "/healthz",
                                     headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    validate(payload, args.expected_revision)
    print(json.dumps({"status": "verified", "revision": args.expected_revision,
                      "health_elapsed_ms": round((time.perf_counter() - started) * 1000)}))


if __name__ == "__main__":
    main()
