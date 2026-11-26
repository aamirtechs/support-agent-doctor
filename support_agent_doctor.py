"""Support agent performance audit CLI.

Reads a support ticket CSV export (from Zendesk, LiveChat,
Freshdesk, or a manual export) and audits every ticket for
the performance problems that quietly cost a support team
its reputation: slow first replies, tickets with no first
reply past the target, slow resolutions, reopened tickets
(once, or repeatedly), escalated tickets, tickets that
took too many replies to solve, and bad data such as
duplicate ticket ids, malformed rows, invalid timestamps,
impossible date orderings, and invalid CSAT values. It
also scores every agent: open load, average first reply
and resolution time, reopen rate, escalation rate, and
CSAT, and flags overloaded agents, slow agents, high
reopen rates, and low CSAT.

Zendesk tracks 25 agent performance metrics, from first
reply time and average handle time to first contact
resolution and reopen rate, and Explore reports them live
inside the paid platform. But nobody audits the exported
ticket file first to say which agents need coaching this
week and which tickets are already breaching. This tool
is that audit: it scores the agents in the export alone,
and never touches your helpdesk.

Each problem is a finding with a ticket id, a rule name,
a severity (error or warning), and a message. Errors are
breaches (slow first reply, no first reply past target,
slow resolution, repeated reopens), impossible dates, and
data that cannot be trusted; warnings are single reopens,
escalations, reply-heavy tickets, and agent-level
patterns worth coaching. --check exits 1 when any error
is found, and --strict also fails on warnings.

Dates are parsed defensively. A bad date is reported as a
finding and the row is still audited on the fields that
did parse, so one bad row never crashes the run.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 support_agent_doctor.py examples/tickets.csv
    python3 support_agent_doctor.py tickets.csv --json --check
    python3 support_agent_doctor.py tickets.csv --as-of 2026-11-18
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone

__version__ = "1.0.0"

DEFAULT_MAX_FIRST_REPLY_HOURS = 4
DEFAULT_MAX_RESOLUTION_HOURS = 48
DEFAULT_MAX_REPLIES = 10
DEFAULT_MAX_OPEN = 15
DEFAULT_MAX_REOPEN_RATE = 20
DEFAULT_MIN_CSAT = 80
DEFAULT_MIN_RATED_TICKETS = 3

KNOWN_STATUSES = {"solved", "closed", "open", "pending", "on-hold",
                  "hold", "new"}
KNOWN_CSAT = {"good", "bad", "none", ""}
OPEN_STATUSES = {"open", "pending", "on-hold", "hold", "new"}
SOLVED_STATUSES = {"solved", "closed"}

TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y",
)


class Finding:
    """One audit finding for one ticket, or for one agent."""

    def __init__(self, ticket, rule, severity, message):
        self.ticket = ticket
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"ticket": self.ticket, "rule": self.rule,
                "severity": self.severity, "message": self.message}

    def __str__(self):
        return "%s [%s] %s: %s" % (self.severity.upper(), self.rule,
                                   self.ticket, self.message)


def parse_timestamp(text):
    """Parse a timestamp string into an aware datetime, or None.

    Accepts ISO 8601 with or without a timezone (a trailing Z is
    handled), plus a few common export formats. A naive timestamp
    is read as UTC. Returns None for an empty string or a value
    that matches no known format, so callers can report it
    instead of crashing.
    """
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_int(text, default=0):
    """Parse an integer string, or the default when unreadable."""
    if text is None:
        return default
    text = text.strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return default


def parse_yes(text):
    """Return True when a yes/no column value means yes."""
    if text is None:
        return False
    return text.strip().lower() in ("yes", "true", "1", "y")


def find_column(header, names):
    """Return the first of names present in header, or None."""
    for name in names:
        if name in header:
            return name
    return None


def parse_csv(path, as_of):
    """Parse a support ticket CSV export.

    Returns (tickets, findings). Each ticket is a dict with
    the id, agent, status, the parsed created, first reply,
    and solved dates, reply and reopen counts, whether it
    was escalated, the CSAT value, and the channel. Rows
    with the wrong number of fields are reported as
    malformed-row errors and skipped, never a crash. A UTF-8
    BOM header is handled. Extra columns are ignored.
    """
    findings = []
    tickets = []
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError("cannot read %s: %s" % (path, exc))
    with handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("%s is empty, no header row found" % path)
        except csv.Error as exc:
            raise ValueError("%s is not a readable CSV file: %s"
                             % (path, exc))
        header = [name.strip() for name in header]
        id_column = find_column(header, ("ticket_id", "id"))
        if id_column is None:
            raise ValueError(
                "%s has no ticket_id or id column (header is: %s)"
                % (path, ", ".join(header)))
        agent_column = find_column(
            header, ("agent", "agent_name", "assignee",
                     "assigned_to"))
        if agent_column is None:
            raise ValueError(
                "%s has no agent column "
                "(header is: %s)" % (path, ", ".join(header)))
        status_column = find_column(header, ("status", "ticket_status"))
        if status_column is None:
            raise ValueError(
                "%s has no status column "
                "(header is: %s)" % (path, ", ".join(header)))
        created_column = find_column(
            header, ("created_at", "created", "created_date"))
        if created_column is None:
            raise ValueError(
                "%s has no created_at column "
                "(header is: %s)" % (path, ", ".join(header)))
        first_reply_column = find_column(
            header, ("first_reply_at", "first_reply", "first_response"))
        solved_column = find_column(
            header, ("solved_at", "solved", "resolved_at",
                     "resolved", "closed_at"))
        replies_column = find_column(
            header, ("replies", "reply_count", "agent_replies",
                     "public_replies"))
        reopens_column = find_column(
            header, ("reopens", "reopen_count", "reopened"))
        escalated_column = find_column(header, ("escalated",))
        csat_column = find_column(
            header, ("csat", "satisfaction", "rating"))
        channel_column = find_column(header, ("channel", "source"))
        seen_ids = set()
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                findings.append(Finding(
                    "row %d" % line_number, "malformed-row", "error",
                    "row has %d fields but the header has %d, "
                    "so the row was skipped" % (len(row), len(header))))
                continue
            cells = dict(zip(header, (cell.strip() for cell in row)))
            ticket_id = cells[id_column]
            if not ticket_id:
                findings.append(Finding(
                    "row %d" % line_number, "missing-ticket-id",
                    "error",
                    "row has no ticket id, so the ticket cannot "
                    "be matched to an agent"))
                ticket_id = "row %d" % line_number
            if ticket_id in seen_ids:
                findings.append(Finding(
                    ticket_id, "duplicate-ticket-id", "error",
                    "ticket id appears more than once in the export"))
            else:
                seen_ids.add(ticket_id)
            agent = cells[agent_column]
            if not agent:
                findings.append(Finding(
                    ticket_id, "missing-agent", "error",
                    "ticket has no agent, so it cannot be "
                    "counted in the per-agent table"))
            status = cells[status_column].lower()
            if status and status not in KNOWN_STATUSES:
                findings.append(Finding(
                    ticket_id, "invalid-status", "error",
                    "status %r is not a known ticket status"
                    % status))
            created = None
            created_raw = cells[created_column]
            if created_raw:
                created = parse_timestamp(created_raw)
                if created is None:
                    findings.append(Finding(
                        ticket_id, "invalid-timestamp", "error",
                        "created date %r is not a readable date"
                        % created_raw))
            first_reply = None
            first_reply_raw = (cells[first_reply_column]
                               if first_reply_column else "")
            if first_reply_raw:
                first_reply = parse_timestamp(first_reply_raw)
                if first_reply is None:
                    findings.append(Finding(
                        ticket_id, "invalid-timestamp", "error",
                        "first reply date %r is not a readable "
                        "date" % first_reply_raw))
            solved = None
            solved_raw = (cells[solved_column]
                          if solved_column else "")
            if solved_raw:
                solved = parse_timestamp(solved_raw)
                if solved is None:
                    findings.append(Finding(
                        ticket_id, "invalid-timestamp", "error",
                        "solved date %r is not a readable date"
                        % solved_raw))
            if created is not None and created > as_of:
                findings.append(Finding(
                    ticket_id, "future-timestamp", "error",
                    "created date %s is after the as-of date %s"
                    % (created.strftime("%Y-%m-%d %H:%M"),
                       as_of.strftime("%Y-%m-%d %H:%M"))))
            if created is not None and first_reply is not None \
                    and first_reply < created:
                findings.append(Finding(
                    ticket_id, "impossible-dates", "error",
                    "first reply %s is before the ticket was "
                    "created %s"
                    % (first_reply.strftime("%Y-%m-%d %H:%M"),
                       created.strftime("%Y-%m-%d %H:%M"))))
            if created is not None and solved is not None \
                    and solved < created:
                findings.append(Finding(
                    ticket_id, "impossible-dates", "error",
                    "solved date %s is before the ticket was "
                    "created %s"
                    % (solved.strftime("%Y-%m-%d %H:%M"),
                       created.strftime("%Y-%m-%d %H:%M"))))
            if first_reply is not None and solved is not None \
                    and solved < first_reply:
                findings.append(Finding(
                    ticket_id, "impossible-dates", "error",
                    "solved date %s is before the first reply %s"
                    % (solved.strftime("%Y-%m-%d %H:%M"),
                       first_reply.strftime("%Y-%m-%d %H:%M"))))
            csat = (cells[csat_column].lower()
                    if csat_column else "")
            if csat not in KNOWN_CSAT:
                findings.append(Finding(
                    ticket_id, "invalid-csat", "error",
                    "CSAT value %r is not good, bad, or none"
                    % csat))
            tickets.append({
                "id": ticket_id,
                "agent": agent,
                "status": status,
                "created": created,
                "first_reply": first_reply,
                "solved": solved,
                "replies": parse_int(
                    cells[replies_column] if replies_column else ""),
                "reopens": parse_int(
                    cells[reopens_column] if reopens_column else ""),
                "escalated": parse_yes(
                    cells[escalated_column]
                    if escalated_column else ""),
                "csat": csat,
                "channel": (cells[channel_column]
                            if channel_column else ""),
                "line": line_number})
    return tickets, findings


def hours_between(start, end):
    """Return the hours from start to end, or None."""
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 3600.0


def audit(tickets, as_of,
          max_first_reply_hours=DEFAULT_MAX_FIRST_REPLY_HOURS,
          max_resolution_hours=DEFAULT_MAX_RESOLUTION_HOURS,
          max_replies=DEFAULT_MAX_REPLIES,
          max_open=DEFAULT_MAX_OPEN,
          max_reopen_rate=DEFAULT_MAX_REOPEN_RATE,
          min_csat=DEFAULT_MIN_CSAT,
          min_rated_tickets=DEFAULT_MIN_RATED_TICKETS):
    """Audit a parsed ticket list and return a list of findings."""
    findings = []
    for ticket in tickets:
        ticket_id = ticket["id"]
        status = ticket["status"]
        created = ticket["created"]
        first_reply = ticket["first_reply"]
        solved = ticket["solved"]
        first_reply_hours = hours_between(created, first_reply)
        resolution_hours = hours_between(created, solved)
        age_hours = None
        if created is not None:
            age_hours = (as_of - created).total_seconds() / 3600.0
        if first_reply_hours is not None and first_reply_hours >= 0:
            if first_reply_hours > max_first_reply_hours:
                findings.append(Finding(
                    ticket_id, "slow-first-reply", "error",
                    "first reply took %.1f hours, past the "
                    "%.1f hour target"
                    % (first_reply_hours, max_first_reply_hours)))
        if first_reply is None and status in OPEN_STATUSES \
                and age_hours is not None \
                and age_hours > max_first_reply_hours:
            findings.append(Finding(
                ticket_id, "no-first-reply-overdue", "error",
                "ticket has waited %.1f hours with no first "
                "reply, past the %.1f hour target"
                % (age_hours, max_first_reply_hours)))
        if resolution_hours is not None and resolution_hours >= 0 \
                and status in SOLVED_STATUSES:
            if resolution_hours > max_resolution_hours:
                findings.append(Finding(
                    ticket_id, "slow-resolution", "error",
                    "resolution took %.1f hours, past the "
                    "%.1f hour target"
                    % (resolution_hours, max_resolution_hours)))
        if ticket["reopens"] >= 2:
            findings.append(Finding(
                ticket_id, "reopened-repeatedly", "error",
                "ticket was reopened %d times, so the first "
                "fix did not hold" % ticket["reopens"]))
        elif ticket["reopens"] == 1:
            findings.append(Finding(
                ticket_id, "reopened-ticket", "warning",
                "ticket was reopened once, so the first fix "
                "did not hold"))
        if ticket["escalated"]:
            findings.append(Finding(
                ticket_id, "escalated-ticket", "warning",
                "ticket was escalated to another agent or team"))
        if ticket["replies"] > max_replies:
            findings.append(Finding(
                ticket_id, "many-replies", "warning",
                "ticket took %d replies to solve, past the "
                "%d reply limit" % (ticket["replies"], max_replies)))
    agents = {}
    for ticket in tickets:
        if ticket["agent"]:
            agents.setdefault(ticket["agent"], []).append(ticket)
    for agent in sorted(agents):
        agent_tickets = agents[agent]
        open_count = sum(1 for item in agent_tickets
                         if item["status"] in OPEN_STATUSES)
        if open_count > max_open:
            findings.append(Finding(
                "agent %s" % agent, "agent-overload", "error",
                "agent has %d open tickets, past the %d "
                "ticket limit" % (open_count, max_open)))
        first_reply_times = []
        for item in agent_tickets:
            value = hours_between(item["created"],
                                  item["first_reply"])
            if value is not None and value >= 0:
                first_reply_times.append(value)
        if first_reply_times:
            average = sum(first_reply_times) / len(first_reply_times)
            if average > max_first_reply_hours:
                findings.append(Finding(
                    "agent %s" % agent, "agent-slow-first-reply",
                    "warning",
                    "agent averages %.1f hours to first reply, "
                    "past the %.1f hour target"
                    % (average, max_first_reply_hours)))
        reopened = sum(1 for item in agent_tickets
                       if item["reopens"] >= 1)
        if agent_tickets:
            reopen_rate = reopened / len(agent_tickets) * 100.0
            if reopen_rate > max_reopen_rate:
                findings.append(Finding(
                    "agent %s" % agent, "agent-high-reopen-rate",
                    "warning",
                    "agent reopened %.1f%% of tickets "
                    "(%d of %d), past the %d%% limit"
                    % (reopen_rate, reopened, len(agent_tickets),
                       max_reopen_rate)))
        rated = [item for item in agent_tickets
                 if item["csat"] in ("good", "bad")]
        if len(rated) >= min_rated_tickets:
            good = sum(1 for item in rated if item["csat"] == "good")
            csat_rate = good / len(rated) * 100.0
            if csat_rate < min_csat:
                findings.append(Finding(
                    "agent %s" % agent, "agent-low-csat", "warning",
                    "agent CSAT is %.1f%% good (%d of %d rated), "
                    "below the %d%% minimum"
                    % (csat_rate, good, len(rated), min_csat)))
    return findings


def summarize(tickets, findings, as_of,
              max_first_reply_hours=DEFAULT_MAX_FIRST_REPLY_HOURS,
              max_resolution_hours=DEFAULT_MAX_RESOLUTION_HOURS,
              max_open=DEFAULT_MAX_OPEN):
    """Return the summary counts for a ticket list and findings."""
    errors = sum(1 for item in findings if item.severity == "error")
    warnings = sum(1 for item in findings
                   if item.severity == "warning")
    solved = sum(1 for item in tickets
                 if item["status"] in SOLVED_STATUSES)
    open_count = sum(1 for item in tickets
                     if item["status"] in OPEN_STATUSES)
    first_reply_times = []
    resolution_times = []
    for ticket in tickets:
        if ticket["created"] is not None \
                and ticket["created"] <= as_of:
            first = hours_between(ticket["created"],
                                  ticket["first_reply"])
            if first is not None and first >= 0:
                first_reply_times.append(first)
            resolved = hours_between(ticket["created"],
                                     ticket["solved"])
            if resolved is not None and resolved >= 0 \
                    and ticket["status"] in SOLVED_STATUSES:
                resolution_times.append(resolved)
    average_first = (sum(first_reply_times) / len(first_reply_times)
                     if first_reply_times else None)
    average_resolution = (sum(resolution_times)
                          / len(resolution_times)
                          if resolution_times else None)
    reopened = sum(1 for item in tickets if item["reopens"] >= 1)
    reopen_rate = (reopened / len(tickets) * 100.0
                   if tickets else 0.0)
    escalated = sum(1 for item in tickets if item["escalated"])
    escalation_rate = (escalated / len(tickets) * 100.0
                       if tickets else 0.0)
    rated = [item for item in tickets
             if item["csat"] in ("good", "bad")]
    good = sum(1 for item in rated if item["csat"] == "good")
    csat_rate = (good / len(rated) * 100.0 if rated else None)
    per_agent = []
    agents = {}
    for ticket in tickets:
        if ticket["agent"]:
            agents.setdefault(ticket["agent"], []).append(ticket)
    for agent in sorted(agents):
        agent_tickets = agents[agent]
        agent_solved = sum(1 for item in agent_tickets
                           if item["status"] in SOLVED_STATUSES)
        agent_open = sum(1 for item in agent_tickets
                         if item["status"] in OPEN_STATUSES)
        agent_first = []
        agent_resolved = []
        for item in agent_tickets:
            if item["created"] is not None \
                    and item["created"] <= as_of:
                first = hours_between(item["created"],
                                      item["first_reply"])
                if first is not None and first >= 0:
                    agent_first.append(first)
                resolved = hours_between(item["created"],
                                         item["solved"])
                if resolved is not None and resolved >= 0 \
                        and item["status"] in SOLVED_STATUSES:
                    agent_resolved.append(resolved)
        agent_average_first = (sum(agent_first) / len(agent_first)
                               if agent_first else None)
        agent_average_resolution = (sum(agent_resolved)
                                    / len(agent_resolved)
                                    if agent_resolved else None)
        agent_reopened = sum(1 for item in agent_tickets
                             if item["reopens"] >= 1)
        agent_reopen_rate = (agent_reopened / len(agent_tickets)
                             * 100.0 if agent_tickets else 0.0)
        agent_escalated = sum(1 for item in agent_tickets
                              if item["escalated"])
        agent_escalation_rate = (agent_escalated
                                 / len(agent_tickets) * 100.0
                                 if agent_tickets else 0.0)
        agent_rated = [item for item in agent_tickets
                       if item["csat"] in ("good", "bad")]
        agent_good = sum(1 for item in agent_rated
                         if item["csat"] == "good")
        agent_csat = (agent_good / len(agent_rated) * 100.0
                      if agent_rated else None)
        per_agent.append({
            "agent": agent,
            "tickets": len(agent_tickets),
            "solved": agent_solved,
            "open": agent_open,
            "average_first_reply_hours":
                (round(agent_average_first, 1)
                 if agent_average_first is not None else None),
            "average_resolution_hours":
                (round(agent_average_resolution, 1)
                 if agent_average_resolution is not None else None),
            "reopen_rate": round(agent_reopen_rate, 1),
            "escalation_rate": round(agent_escalation_rate, 1),
            "csat_good_rate":
                (round(agent_csat, 1)
                 if agent_csat is not None else None)})
    return {"tickets": len(tickets),
            "findings": len(findings),
            "errors": errors,
            "warnings": warnings,
            "solved": solved,
            "open": open_count,
            "agents": len(agents),
            "average_first_reply_hours":
                (round(average_first, 1)
                 if average_first is not None else None),
            "average_resolution_hours":
                (round(average_resolution, 1)
                 if average_resolution is not None else None),
            "reopen_rate": round(reopen_rate, 1),
            "escalation_rate": round(escalation_rate, 1),
            "csat_good_rate":
                (round(csat_rate, 1)
                 if csat_rate is not None else None),
            "per_agent": per_agent}


def format_hours(value):
    """Format an average hours value, or n/a when there is none."""
    if value is None:
        return "n/a"
    return "%.1f hours" % value


def format_rate(value):
    """Format a percentage value, or n/a when there is none."""
    if value is None:
        return "n/a"
    return "%.1f%%" % value


def render_text(tickets, findings, summary):
    """Render the text report."""
    lines = [str(item) for item in findings]
    lines.append("")
    lines.append("Tickets: %(tickets)d, findings: %(findings)d, "
                 "errors: %(errors)d, warnings: %(warnings)d"
                 % summary)
    lines.append("Solved: %(solved)d, open: %(open)d, agents: "
                 "%(agents)d" % summary)
    lines.append("Average first reply: %s, average "
                 "resolution: %s"
                 % (format_hours(summary["average_first_reply_hours"]),
                    format_hours(
                        summary["average_resolution_hours"])))
    lines.append("Reopen rate: %.1f%%, escalation rate: %.1f%%, "
                 "CSAT good rate: %s"
                 % (summary["reopen_rate"],
                    summary["escalation_rate"],
                    format_rate(summary["csat_good_rate"])))
    lines.append("")
    lines.append("Per-agent summary:")
    for row in summary["per_agent"]:
        lines.append(
            "%s: %d tickets, %d solved, %d open, first reply "
            "%s, resolution %s, reopen %.1f%%, "
            "escalation %.1f%%, CSAT %s"
            % (row["agent"], row["tickets"], row["solved"],
               row["open"],
               format_hours(row["average_first_reply_hours"]),
               format_hours(row["average_resolution_hours"]),
               row["reopen_rate"], row["escalation_rate"],
               format_rate(row["csat_good_rate"])))
    if summary["findings"] == 0:
        lines.append("")
        lines.append("All tickets clean.")
    return "\n".join(lines) + "\n"


def render_json(tickets, findings, summary):
    """Render the JSON report."""
    report = dict(summary)
    report["findings"] = [item.as_dict() for item in findings]
    return json.dumps(report, indent=2) + "\n"


def build_parser():
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog="support-agent-doctor",
        description="Audit a support ticket CSV export for "
                    "agent performance: slow first replies, slow "
                    "resolutions, reopens, escalations, and CSAT.")
    parser.add_argument("csv_file", help="support ticket CSV "
                        "export to audit")
    parser.add_argument("--max-first-reply-hours", type=float,
                        default=DEFAULT_MAX_FIRST_REPLY_HOURS,
                        help="a first reply slower than this many "
                        "hours is a breach "
                        "(default: %.1f)"
                        % DEFAULT_MAX_FIRST_REPLY_HOURS)
    parser.add_argument("--max-resolution-hours", type=float,
                        default=DEFAULT_MAX_RESOLUTION_HOURS,
                        help="a resolution slower than this many "
                        "hours is a breach "
                        "(default: %.1f)"
                        % DEFAULT_MAX_RESOLUTION_HOURS)
    parser.add_argument("--max-replies", type=int,
                        default=DEFAULT_MAX_REPLIES,
                        help="a ticket with more replies than this "
                        "took too many replies "
                        "(default: %d)" % DEFAULT_MAX_REPLIES)
    parser.add_argument("--max-open", type=int,
                        default=DEFAULT_MAX_OPEN,
                        help="an agent with more open tickets than "
                        "this is overloaded "
                        "(default: %d)" % DEFAULT_MAX_OPEN)
    parser.add_argument("--max-reopen-rate", type=int,
                        default=DEFAULT_MAX_REOPEN_RATE,
                        help="an agent reopening more than this "
                        "percentage of tickets needs coaching "
                        "(default: %d)" % DEFAULT_MAX_REOPEN_RATE)
    parser.add_argument("--min-csat", type=int,
                        default=DEFAULT_MIN_CSAT,
                        help="an agent below this CSAT good rate "
                        "needs coaching (default: %d)"
                        % DEFAULT_MIN_CSAT)
    parser.add_argument("--as-of", default=None,
                        help="date to compare timestamps against, "
                        "for example 2026-11-18 (default: now)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", default=None,
                        help="write the report to a file")
    return parser


def main(argv=None):
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    if args.max_first_reply_hours < 0:
        print("error: --max-first-reply-hours must be at least 0",
              file=sys.stderr)
        return 2
    if args.max_resolution_hours < 0:
        print("error: --max-resolution-hours must be at least 0",
              file=sys.stderr)
        return 2
    if args.max_replies < 0:
        print("error: --max-replies must be at least 0",
              file=sys.stderr)
        return 2
    if args.max_open < 0:
        print("error: --max-open must be at least 0",
              file=sys.stderr)
        return 2
    if args.max_reopen_rate < 0 or args.max_reopen_rate > 100:
        print("error: --max-reopen-rate must be from 0 to 100",
              file=sys.stderr)
        return 2
    if args.min_csat < 0 or args.min_csat > 100:
        print("error: --min-csat must be from 0 to 100",
              file=sys.stderr)
        return 2
    if args.as_of is None:
        as_of = datetime.now(timezone.utc)
    else:
        as_of = parse_timestamp(args.as_of)
        if as_of is None:
            print("error: --as-of %r is not a readable date"
                  % args.as_of, file=sys.stderr)
            return 2
    try:
        tickets, findings = parse_csv(args.csv_file, as_of)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    findings.extend(audit(tickets, as_of,
                          max_first_reply_hours=
                          args.max_first_reply_hours,
                          max_resolution_hours=
                          args.max_resolution_hours,
                          max_replies=args.max_replies,
                          max_open=args.max_open,
                          max_reopen_rate=args.max_reopen_rate,
                          min_csat=args.min_csat))
    summary = summarize(tickets, findings, as_of,
                        max_first_reply_hours=
                        args.max_first_reply_hours,
                        max_resolution_hours=
                        args.max_resolution_hours,
                        max_open=args.max_open)
    if args.json:
        report = render_json(tickets, findings, summary)
    else:
        report = render_text(tickets, findings, summary)
    if args.out is not None:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(report)
        except OSError as exc:
            print("error: cannot write %s: %s" % (args.out, exc),
                  file=sys.stderr)
            return 2
    else:
        sys.stdout.write(report)
    if args.check:
        if summary["errors"] > 0:
            return 1
        if args.strict and summary["warnings"] > 0:
            return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
