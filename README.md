# support-agent-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/support-agent-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/support-agent-doctor/issues)

A zero-dependency Python CLI that audits a support ticket
CSV export for agent performance: slow first replies,
tickets with no first reply past the target, slow
resolutions, reopened tickets (once, or repeatedly),
escalated tickets, tickets that took too many replies to
solve, and bad data such as duplicate ticket ids,
malformed rows, invalid timestamps, impossible date
orderings, and invalid CSAT values. It also scores every
agent (open load, average first reply and resolution
time, reopen rate, escalation rate, and CSAT) and flags
overloaded agents, slow agents, high reopen rates, and
low CSAT.

Zendesk tracks 25 agent performance metrics, from first
reply time and average handle time to first contact
resolution and reopen rate, and Explore reports them live
inside the paid platform. But nobody audits the exported
ticket file first to say which agents need coaching this
week and which tickets are already breaching. This tool
is that audit: it scores the agents in the export alone,
and never touches your helpdesk.

## Install

Requires Python 3.10 or newer. No dependencies beyond the
standard library.

```bash
pip install support-agent-doctor
```

Or run it straight from the source checkout:

```bash
python3 support_agent_doctor.py examples/tickets.csv
```

## Input format

A CSV export with a header row, from Zendesk, LiveChat,
Freshdesk, or a manual export. Columns used: `ticket_id`
(or `id`), `agent` (or `agent_name`, `assignee`),
`status` (or `ticket_status`), `created_at` (or
`created`), `first_reply_at` (or `first_reply`),
`solved_at` (or `solved`, `resolved_at`), `replies` (or
`reply_count`), `reopens` (or `reopen_count`),
`escalated`, `csat` (or `satisfaction`), and `channel`
(or `source`). Extra columns are ignored, so a full
ticket export works as-is. A UTF-8 BOM header is handled.
Only `ticket_id`, `agent`, `status`, and `created_at` are
required; the other columns are optional, and the checks
that need a missing column are skipped.

`created_at` also accepts `created_date`, `first_reply_at`
also accepts `first_response`, `solved_at` also accepts
`resolved` or `closed_at`, `replies` also accepts
`agent_replies` or `public_replies`, and `csat` also
accepts `rating`.

Dates accept ISO 8601 with or without a timezone
(`2026-11-17 10:00`, `2026-11-17T10:00:00Z`,
`2026-11-17`), plus day/month/year and month/day/year
forms. A date with no timezone is read as UTC. CSAT
accepts `good`, `bad`, or `none` (an empty value means
unrated). An `escalated` value of `yes`, `true`, `1`, or
`y` counts as escalated.

```csv
ticket_id,agent,status,created_at,first_reply_at,solved_at,replies,reopens,escalated,csat,channel
T-101,Ana,solved,2026-11-17 09:00,2026-11-17 09:30,2026-11-17 14:00,3,0,no,good,email
T-102,Ana,solved,2026-11-16 09:00,2026-11-17 06:00,2026-11-17 12:00,5,0,no,good,chat
T-103,Ben,solved,2026-11-15 09:00,2026-11-15 10:00,2026-11-17 10:00,12,1,no,bad,email
T-104,Ben,open,2026-11-16 09:00,,,,0,0,no,bad,chat
T-105,Cara,solved,2026-11-14 09:00,2026-11-14 09:15,2026-11-14 11:00,2,0,no,good,email
```

## What it checks

Errors, the ones that mean a ticket is breaching now or
data that cannot be trusted:

* `slow-first-reply`: a first reply slower than
  `--max-first-reply-hours` (default 4).
* `no-first-reply-overdue`: an open, pending, on-hold,
  or new ticket with no first reply at all, older than
  the first reply target.
* `slow-resolution`: a solved or closed ticket whose
  resolution took longer than `--max-resolution-hours`
  (default 48).
* `reopened-repeatedly`: a ticket reopened 2 or more
  times, so the first fix did not hold.
* `agent-overload`: an agent with more than `--max-open`
  (default 15) open tickets.
* `duplicate-ticket-id`: the same ticket id twice in the
  export.
* `missing-ticket-id`: a row with no ticket id, so the
  ticket cannot be matched to an agent.
* `missing-agent`: a ticket with no agent, so it cannot
  be counted in the per-agent table.
* `invalid-timestamp`: a date field that matches no known
  format. The row is still audited on the fields that did
  parse.
* `future-timestamp`: a `created_at` after `--as-of`
  (default now).
* `impossible-dates`: a first reply before the ticket was
  created, a solved date before the ticket was created,
  or a solved date before the first reply.
* `invalid-status`: a status that is not a known ticket
  status (solved, closed, open, pending, on-hold, hold,
  new).
* `invalid-csat`: a CSAT value that is not good, bad, or
  none.
* `malformed-row`: a row with the wrong number of fields.
  The row is skipped and reported, never a crash.

Warnings, tickets and agents worth coaching:

* `reopened-ticket`: a ticket reopened once.
* `escalated-ticket`: a ticket escalated to another
  agent or team.
* `many-replies`: a ticket with more than `--max-replies`
  (default 10) replies.
* `agent-slow-first-reply`: an agent averaging more than
  the first reply target.
* `agent-high-reopen-rate`: an agent reopening more than
  `--max-reopen-rate` (default 20%) of tickets.
* `agent-low-csat`: an agent below the `--min-csat`
  (default 80%) good rate, counted only for agents with
  at least 3 rated tickets.

The summary reports the solved and open counts, the
agent count, the average first reply and resolution
times, the reopen and escalation rates, the CSAT good
rate, and a per-agent table (tickets, solved, open,
average first reply, average resolution, reopen rate,
escalation rate, CSAT).

## Usage

```bash
python3 support_agent_doctor.py examples/tickets.csv --as-of 2026-11-18
```

Captured output:

```
ERROR [impossible-dates] T-110: first reply 2026-11-17 09:00 is before the ticket was created 2026-11-17 10:00
ERROR [impossible-dates] T-111: solved date 2026-11-15 09:00 is before the ticket was created 2026-11-16 09:00
ERROR [impossible-dates] T-111: solved date 2026-11-15 09:00 is before the first reply 2026-11-16 09:30
ERROR [invalid-timestamp] T-112: created date 'not-a-date' is not a readable date
ERROR [future-timestamp] T-113: created date 2026-12-01 09:00 is after the as-of date 2026-11-18 00:00
ERROR [duplicate-ticket-id] T-101: ticket id appears more than once in the export
ERROR [malformed-row] row 16: row has 12 fields but the header has 11, so the row was skipped
ERROR [missing-ticket-id] row 17: row has no ticket id, so the ticket cannot be matched to an agent
ERROR [missing-agent] T-115: ticket has no agent, so it cannot be counted in the per-agent table
ERROR [invalid-csat] T-116: CSAT value 'weird' is not good, bad, or none
ERROR [slow-first-reply] T-102: first reply took 21.0 hours, past the 4.0 hour target
ERROR [slow-resolution] T-103: resolution took 49.0 hours, past the 48.0 hour target
WARNING [reopened-ticket] T-103: ticket was reopened once, so the first fix did not hold
WARNING [many-replies] T-103: ticket took 12 replies to solve, past the 10 reply limit
ERROR [no-first-reply-overdue] T-104: ticket has waited 39.0 hours with no first reply, past the 4.0 hour target
ERROR [reopened-repeatedly] T-106: ticket was reopened 2 times, so the first fix did not hold
WARNING [escalated-ticket] T-106: ticket was escalated to another agent or team
ERROR [no-first-reply-overdue] T-108: ticket has waited 40.0 hours with no first reply, past the 4.0 hour target
ERROR [no-first-reply-overdue] T-117: ticket has waited 15.0 hours with no first reply, past the 4.0 hour target
WARNING [agent-slow-first-reply] agent Ana: agent averages 5.6 hours to first reply, past the 4.0 hour target
WARNING [agent-high-reopen-rate] agent Ben: agent reopened 25.0% of tickets (1 of 4), past the 20% limit
WARNING [agent-low-csat] agent Ben: agent CSAT is 33.3% good (1 of 3 rated), below the 80% minimum
WARNING [agent-high-reopen-rate] agent Cara: agent reopened 33.3% of tickets (1 of 3), past the 20% limit

Tickets: 19, findings: 23, errors: 16, warnings: 7
Solved: 13, open: 6, agents: 4
Average first reply: 2.0 hours, average resolution: 10.1 hours
Reopen rate: 10.5%, escalation rate: 5.3%, CSAT good rate: 84.6%

Per-agent summary:
Ana: 6 tickets, 5 solved, 1 open, first reply 5.6 hours, resolution 8.8 hours, reopen 0.0%, escalation 0.0%, CSAT 100.0%
Ben: 4 tickets, 3 solved, 1 open, first reply 0.6 hours, resolution 24.7 hours, reopen 25.0%, escalation 0.0%, CSAT 33.3%
Cara: 3 tickets, 3 solved, 0 open, first reply 0.3 hours, resolution 1.5 hours, reopen 33.3%, escalation 33.3%, CSAT 100.0%
Dan: 5 tickets, 1 solved, 4 open, first reply 0.2 hours, resolution n/a, reopen 0.0%, escalation 0.0%, CSAT 100.0%
```

The sample has 20 rows; the malformed row 16 is skipped,
so 19 tickets are audited. The headline numbers are 3
tickets with no first reply past the target (Ben and Dan
each left one waiting about 40 hours), 1 slow first reply
at 21.0 hours, 1 slow resolution at 49.0 hours, 1 ticket
reopened twice, and 4 agent-level warnings: Ana averages
5.6 hours to first reply, Ben reopens 25.0% of tickets
and sits at 33.3% CSAT, and Cara reopens 33.3%. Dan carries 4 open tickets and his
only solved ticket is future-dated, so it is left out of
the averages and his resolution shows n/a.

Use it as a CI gate: `--check` exits 1 when any error is
found, and 0 otherwise. On the sample above it exits 1:

```bash
python3 support_agent_doctor.py examples/tickets.csv --as-of 2026-11-18 --check
```

On `examples/clean.csv`, five clean tickets, it exits 0:

```
Tickets: 5, findings: 0, errors: 0, warnings: 0
Solved: 4, open: 1, agents: 3
Average first reply: 0.4 hours, average resolution: 3.0 hours
Reopen rate: 0.0%, escalation rate: 0.0%, CSAT good rate: 100.0%

Per-agent summary:
Ana: 2 tickets, 2 solved, 0 open, first reply 0.5 hours, resolution 4.0 hours, reopen 0.0%, escalation 0.0%, CSAT 100.0%
Ben: 2 tickets, 1 solved, 1 open, first reply 0.3 hours, resolution 2.0 hours, reopen 0.0%, escalation 0.0%, CSAT 100.0%
Cara: 1 tickets, 1 solved, 0 open, first reply 0.2 hours, resolution 2.0 hours, reopen 0.0%, escalation 0.0%, CSAT 100.0%

All tickets clean.
```

With `--strict`, `--check` also fails on warnings.
`examples/warnings-only.csv` has one reopened ticket,
one escalated ticket, and one agent with a 100% reopen
rate on a single ticket, so it passes `--check` (exit 0)
and fails `--check --strict` (exit 1).
With a lower open-ticket limit the overload flag fires:

```bash
python3 support_agent_doctor.py examples/tickets.csv --as-of 2026-11-18 --max-open 2
```

Captured output (only the new line is shown in full below;
the rest of the output is identical to the default run):

```
ERROR [agent-overload] agent Dan: agent has 4 open tickets, past the 2 ticket limit

Tickets: 19, findings: 24, errors: 17, warnings: 7
Solved: 13, open: 6, agents: 4
Average first reply: 2.0 hours, average resolution: 10.1 hours
Reopen rate: 10.5%, escalation rate: 5.3%, CSAT good rate: 84.6%

Per-agent summary:
Ana: 6 tickets, 5 solved, 1 open, first reply 5.6 hours, resolution 8.8 hours, reopen 0.0%, escalation 0.0%, CSAT 100.0%
Ben: 4 tickets, 3 solved, 1 open, first reply 0.6 hours, resolution 24.7 hours, reopen 25.0%, escalation 0.0%, CSAT 33.3%
Cara: 3 tickets, 3 solved, 0 open, first reply 0.3 hours, resolution 1.5 hours, reopen 33.3%, escalation 33.3%, CSAT 100.0%
Dan: 5 tickets, 1 solved, 4 open, first reply 0.2 hours, resolution n/a, reopen 0.0%, escalation 0.0%, CSAT 100.0%
```

`--json` emits the summary and the findings as JSON, and
`--out` writes the report to a file. JSON for the
warnings-only file:

```json
{
  "tickets": 3,
  "findings": [
    {
      "ticket": "T-401",
      "rule": "reopened-ticket",
      "severity": "warning",
      "message": "ticket was reopened once, so the first fix did not hold"
    },
    {
      "ticket": "T-403",
      "rule": "escalated-ticket",
      "severity": "warning",
      "message": "ticket was escalated to another agent or team"
    },
    {
      "ticket": "agent Ana",
      "rule": "agent-high-reopen-rate",
      "severity": "warning",
      "message": "agent reopened 100.0% of tickets (1 of 1), past the 20% limit"
    }
  ],
  "errors": 0,
  "warnings": 3,
  "solved": 2,
  "open": 1,
  "agents": 2,
  "average_first_reply_hours": 0.4,
  "average_resolution_hours": 4.0,
  "reopen_rate": 33.3,
  "escalation_rate": 33.3,
  "csat_good_rate": 100.0,
  "per_agent": [
    {
      "agent": "Ana",
      "tickets": 1,
      "solved": 1,
      "open": 0,
      "average_first_reply_hours": 0.5,
      "average_resolution_hours": 5.0,
      "reopen_rate": 100.0,
      "escalation_rate": 0.0,
      "csat_good_rate": 100.0
    },
    {
      "agent": "Ben",
      "tickets": 2,
      "solved": 1,
      "open": 1,
      "average_first_reply_hours": 0.3,
      "average_resolution_hours": 3.0,
      "reopen_rate": 0.0,
      "escalation_rate": 50.0,
      "csat_good_rate": 100.0
    }
  ]
}
```

## Options

| Flag | Meaning |
| --- | --- |
| `--max-first-reply-hours` | A first reply slower than this many hours is a breach (default: 4.0) |
| `--max-resolution-hours` | A resolution slower than this many hours is a breach (default: 48.0) |
| `--max-replies` | A ticket with more replies than this took too many replies (default: 10) |
| `--max-open` | An agent with more open tickets than this is overloaded (default: 15) |
| `--max-reopen-rate` | An agent reopening more than this percentage of tickets needs coaching (default: 20) |
| `--min-csat` | An agent below this CSAT good rate needs coaching (default: 80) |
| `--as-of` | Date to compare timestamps against, for example 2026-11-18 (default: now) |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

## Edge cases

* A row with too many or too few fields is a malformed-row
  error and is skipped; the rest of the file is still
  audited.
* A bad date is an error, and the row is still audited on
  the fields that did parse, so one bad value never hides
  the other problems on the ticket. A ticket with an
  unreadable created date is left out of the age and
  average calculations, and a ticket with a negative
  first reply or resolution time is left out of the
  averages (the impossible-dates error already covers
  it).
* The first reply and resolution averages count only
  tickets created on or before `--as-of`, so a
  future-dated ticket never pulls the averages forward.
* The no-first-reply check only fires for open, pending,
  on-hold, hold, or new tickets; a solved ticket with no
  recorded first reply is not flagged, since the reply
  may simply be missing from the export.
* The agent CSAT flag needs at least 3 rated tickets, so
  a new agent with one bad rating is not called out.
* A ticket with no agent is still audited on its own
  fields, but it is left out of the per-agent table and
  the agent-level flags.
* A blank line in the file is skipped silently.
* `--as-of` makes runs reproducible: without it, the
  future-timestamp and no-first-reply checks compare
  against the current time.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

70 tests, all passing: timestamp parsing, integer and
yes/no parsing, header aliases and BOM handling,
malformed rows, duplicate and missing ticket ids, missing
agents, invalid timestamps and CSAT values, future
timestamps, impossible date orderings, slow and overdue
first replies with the target boundary, slow resolutions
with the boundary and the open-ticket exception, single
and repeated reopens, escalations, reply counts, agent
overload (open plus pending), agent slow first replies,
agent reopen rates, agent CSAT with the minimum-rated
rule, summary totals and per-agent tables, text and JSON
output, `--out` file output, `--max-first-reply-hours`,
`--max-reopen-rate`, `--min-csat`, and `--max-open`
flags, and `--check` and `--strict` exit codes. The same
70 tests pass under pytest.

## License

MIT. See [LICENSE](LICENSE).
