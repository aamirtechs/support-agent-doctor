# Changelog

## 1.0.0 - 2026-11-21

Initial release.

* Agent performance audit over a support ticket CSV
  export: slow first replies, tickets with no first
  reply past the target, slow resolutions, reopened
  tickets (once, or repeatedly), escalated tickets, and
  tickets that took too many replies to solve.
* Per-agent scoring: open load, average first reply and
  resolution time, reopen rate, escalation rate, and
  CSAT, with overload, slow first reply, high reopen
  rate, and low CSAT flags.
* Data quality checks: duplicate and missing ticket ids,
  missing agents, malformed rows, invalid timestamps and
  CSAT values, future timestamps, impossible date
  orderings, and unknown statuses.
* Defensive timestamp parsing (ISO 8601 with or without
  a timezone, plus common day/month/year forms); a bad
  row is reported as a finding and never crashes the
  run. UTF-8 BOM headers and extra columns handled.
* Findings carry a ticket id, a rule name, a severity
  (error or warning), and a message; errors and warnings
  are counted in the summary.
* Text and --json output, --out file output,
  --max-first-reply-hours, --max-resolution-hours,
  --max-replies, --max-open, --max-reopen-rate, --min-csat,
  and --as-of thresholds, and a --check CI gate that
  exits 1 on errors (and on warnings with --strict).
* Zero dependencies, Python 3.10 or newer.
