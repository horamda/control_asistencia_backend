from pathlib import Path

from flask import Flask, render_template


def test_shared_form_renders_inheritance_false_and_numeric_parameters():
    app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / "templates"))
    app.jinja_env.globals["csrf_token"] = lambda: "test-token"
    with app.test_request_context("/"):
        html = render_template("partials/facial_draft.html", data={
            "facial_allowed": True, "facial_ready": True,
            "facial_policy_revision": 2, "facial_draft_mode": "inherit",
            "facial_draft_values": {"on_exit": False, "max_attempts": 4},
            "facial_preview": {
                "requested": {"mode": "trial", "on_entry": True, "on_exit": False,
                              "max_attempts": 4, "timeout_seconds": 30},
                "origins": {"mode": "company", "on_exit": "employee"},
            },
        })
    assert html.count("<form ") == 1
    assert 'name="csrf_token" value="test-token"' in html
    assert 'name="facial_revision" value="2"' in html
    assert 'value="false" selected' in html
    assert 'value="4"' in html
    assert "Estado efectivo:" in html and "<strong>desactivado</strong>" in html
    assert "empresa" in html
    assert "name=\"facial_timeout_seconds\"" in html


def test_no_facial_section_for_unauthorized_viewer():
    app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / "templates"))
    with app.test_request_context("/"):
        html = render_template("partials/facial_draft.html", data={"facial_allowed": False})
    assert "<form" not in html
    assert "facial_mode" not in html
