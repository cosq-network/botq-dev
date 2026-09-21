# Phase 4 Accessibility Evidence

The Phase 4 workbench provides an accessibility baseline for the core review and acceptance
workflow. It uses semantic headings, labelled form controls, visible keyboard focus, a skip link,
responsive layout, and status announcements.

Run the deterministic baseline from the repository root:

```sh
python scripts/validate_accessibility.py --json
```

The check validates the workbench template and stylesheet for document language/title, viewport,
skip-link target, labelled controls, image alternative text, inline event handlers, visible focus,
and heading structure. It is intentionally conservative and produces machine-readable evidence.

For the API-only pilot, this automated baseline may satisfy the Gate 5 accessibility check only when
project policy and gate evidence explicitly choose automated acceptance. Otherwise, QA should supplement
it with manual WCAG 2.2 AA review using keyboard-only navigation, at least one screen reader, 200%
zoom/reflow, reduced motion, contrast inspection, error recovery, and the complete mockup -> preview
-> HAT -> defect workflow. Record the browser, assistive technology, test date, reviewer, scenarios,
findings, and remediation evidence in the acceptance session.
