"""Run deterministic accessibility checks against the Phase 4 workbench template.

This is an evidence-producing baseline, not a replacement for manual WCAG 2.2
AA review with assistive technology and keyboard-only scenarios.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


class WorkbenchAccessibilityParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.html_lang = None
        self.title = False
        self.title_text = []
        self.viewport = False
        self.ids = set()
        self.skip_link = False
        self.skip_target = False
        self.controls = []
        self.labels = 0
        self.label_depth = 0
        self.images_missing_alt = []
        self.inline_handlers = []
        self.headings = []
        self.focus_visible = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "html":
            self.html_lang = values.get("lang")
        if "id" in values:
            self.ids.add(values["id"])
        if tag == "title":
            self.title = True
        if tag == "meta" and values.get("name", "").lower() == "viewport":
            self.viewport = True
        if tag == "a" and values.get("href") == "#workbench":
            self.skip_link = True
        if tag in {"input", "select", "textarea"}:
            self.controls.append((tag, values.get("id"), self.label_depth > 0))
        if tag == "label":
            self.labels += 1
            self.label_depth += 1
        if tag == "img" and not values.get("alt", "").strip():
            self.images_missing_alt.append(values.get("src", "<unknown>"))
        for name in values:
            if name.lower().startswith("on"):
                self.inline_handlers.append(name)
        if re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))

    def handle_endtag(self, tag):
        if tag == "title":
            self.title = False
        if tag == "label" and self.label_depth:
            self.label_depth -= 1

    def handle_data(self, data):
        if self.title:
            self.title_text.append(data)

    def finish(self, css: str):
        self.skip_target = "workbench" in self.ids
        self.focus_visible = ":focus-visible" in css
        checks = {
            "document_language": bool(self.html_lang),
            "document_title": bool("".join(self.title_text).strip()),
            "viewport": self.viewport,
            "skip_link_target": self.skip_link and self.skip_target,
            "form_controls_have_labels": bool(self.controls)
            and all(item[2] for item in self.controls),
            "images_have_alt": not self.images_missing_alt,
            "no_inline_event_handlers": not self.inline_handlers,
            "visible_keyboard_focus": self.focus_visible,
            "single_h1": self.headings.count(1) == 1,
        }
        return checks


def validate(template: Path, stylesheet: Path) -> dict:
    parser = WorkbenchAccessibilityParser()
    parser.feed(template.read_text(encoding="utf-8"))
    checks = parser.finish(stylesheet.read_text(encoding="utf-8"))
    return {
        "template": str(template),
        "stylesheet": str(stylesheet),
        "checks": checks,
        "passed": all(checks.values()),
        "manual_review_required": True,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template", type=Path, default=root / "backend/app/templates/workbench.html"
    )
    parser.add_argument(
        "--stylesheet", type=Path, default=root / "backend/app/static/workbench.css"
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = validate(args.template, args.stylesheet)
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for name, passed in report["checks"].items():
            print(f"{'PASS' if passed else 'FAIL'} {name}")
        print(
            "PASS automated accessibility baseline"
            if report["passed"]
            else "FAIL automated accessibility baseline"
        )
        print("Manual WCAG 2.2 AA review remains required.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
