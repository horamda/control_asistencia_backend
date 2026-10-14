import xml.etree.ElementTree as ET
from scripts.check_release_tests import REQUIRED, check


def report(tmp_path, *, omit=None, status=None):
    root = ET.Element("testsuite")
    for name in sorted(REQUIRED - ({omit} if omit else set())):
        case = ET.SubElement(root, "testcase", classname=name, name="flow")
        if name == "tests.test_epp" and status:
            ET.SubElement(case, status)
    path = tmp_path / "report.xml"
    ET.ElementTree(root).write(path)
    return path


def test_accepts_executed_critical_flows(tmp_path):
    assert check(report(tmp_path)) == []


def test_rejects_missing_flow(tmp_path):
    assert check(report(tmp_path, omit="tests.test_epp"))


def test_rejects_skipped_or_failed_critical_flow(tmp_path):
    for status in ("skipped", "failure", "error"):
        assert check(report(tmp_path, status=status))
