# sync receipt

- at: 2026-11-02T03:14:08
- branch: arena/03860148-jevharness
- head: ac718a5
- message: docs: advisor report - problem list + methodological difficulties (2026-11-02)
- push: failed
- criteria: passed
  - [PASS] require_files:results/desktop/md_*.json (1 hit(s))
  - [PASS] forbid_files:results/desktop/*.xtc (0 hit(s))
  - [PASS] forbid_files:results/desktop/*.tpr (0 hit(s))
  - [PASS] require_json:md_YLSLLQR_20261102-020641.json[status] (status = 'ok')
  - [PASS] require_json:md_YLSLLQR_20261102-020641.json[target_ns] (target_ns = 100.0)
  - [PASS] require_json:md_YLSLLQR_20261102-020641.json[performance_ns_per_day] (performance_ns_per_day = 5814.269)
  - [PASS] require_json:md_YLSLLQR_20261102-020641.json[final_report.finished] (final_report.finished = True)
