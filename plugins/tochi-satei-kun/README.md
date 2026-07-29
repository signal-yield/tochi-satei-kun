# tochi-satei-kun Codex Plugin

This package exposes the canonical `skills/tochi-satei-kun` workflow as a Codex skills-only plugin.

`tochi-satei-kun` is an Apache-2.0 local-first OSS tool for preliminary Japanese land brokerage valuation support. It calls the repository's canonical CLI, `skills/tochi-satei-kun/scripts/main.py`, and generates Excel and JSON outputs from user-provided property, MLIT transaction, and L01 land-price-publication files.

The tool uses white-box hedonic regression and comparable transaction analysis. It does not send input files to external services. Outputs are not real-estate appraisal opinions. Site conditions, legal restrictions, rights, and other material facts require separate confirmation, and final decisions remain with the user.

The packaged skill is synchronized from the canonical skill by:

```bash
python scripts/sync_codex_plugin_skill.py
python scripts/sync_codex_plugin_skill.py --check
```

Canonical CLI example:

```bash
python skills/tochi-satei-kun/scripts/main.py ^
  skills/tochi-satei-kun/samples/sample_property.json ^
  skills/tochi-satei-kun/samples/sample_mlit.csv ^
  skills/tochi-satei-kun/samples/sample_koji.csv ^
  --out work/tochi-satei-output ^
  --json-out work/tochi-satei-output/sample.json
```
