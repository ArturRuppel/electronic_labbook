# `sample_data/` — synthetic dataset

A small, **synthetic** dataset (no real research data, no PII) so the application
**runs out of the box** for anyone who clones the public repo:

- a handful of fake experiments following the SDGL naming grammar
  (`AA00_raw`, `AA00_analysis_tfm`, …),
- one or two example reports and protocols,
- a `sdgl.toml` pointing the scan roots at this folder.

This is what a new contributor sees before they wire up their own data repo. It is
populated as the engine and generators land (Roadmap steps 4–5); for now this is a
placeholder describing the intent.
