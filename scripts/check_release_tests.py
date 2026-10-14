"""Reject incomplete critical-flow test reports before releasing a backend."""
import sys
import xml.etree.ElementTree as ET

REQUIRED = {
    "tests.test_epp",
    "tests.test_epp_concepts",
    "tests.test_audit_database",
    "tests.test_reintegros",
    "tests.test_reintegros_monthly",
    "tests.test_seguridad_mobile_dashboard",
    "tests.test_carga_integration",
}


def check(*paths):
    cases = [case for path in paths for case in ET.parse(path).iter("testcase")]
    missing = REQUIRED - {case.get("classname") for case in cases}
    problems = [f"Missing test module: {name}" for name in sorted(missing)]
    for case in cases:
        failed = case.find("failure") is not None or case.find("error") is not None
        skipped = case.find("skipped") is not None
        if failed or (skipped and case.get("classname") in REQUIRED):
            problems.append(f"Not validated: {case.get('classname')}.{case.get('name')}")
    return problems


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: check_release_tests.py report.xml [report2.xml ...]")
    problems = check(*sys.argv[1:])
    for problem in problems:
        print(problem)
    if not problems:
        print("Critical flows executed successfully; no skipped critical tests.")
    raise SystemExit(bool(problems))
