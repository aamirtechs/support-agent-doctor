"""Tests for support_agent_doctor."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import support_agent_doctor as doctor

AS_OF = datetime(2026, 11, 18, tzinfo=timezone.utc)

HEADER = ("ticket_id,agent,status,created_at,first_reply_at,"
          "solved_at,replies,reopens,escalated,csat,channel\n")


def write_csv(body, directory=None):
    """Write body to a temp CSV file and return its path."""
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False,
        dir=directory, encoding="utf-8")
    handle.write(body)
    handle.close()
    return handle.name


def row(ticket_id="T-1", agent="Ana", status="solved",
        created="2026-11-17 09:00", first_reply="2026-11-17 09:30",
        solved="2026-11-17 14:00", replies="3", reopens="0",
        escalated="no", csat="good", channel="email"):
    """Build one CSV data row."""
    return ",".join((ticket_id, agent, status, created,
                     first_reply, solved, replies, reopens,
                     escalated, csat, channel)) + "\n"


def run_cli(argv):
    """Run main with argv and capture stdout, return (code, text)."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = doctor.main(argv)
    return code, buffer.getvalue()


def parse_and_audit(body, **kwargs):
    """Parse body and audit it, return (tickets, findings)."""
    path = write_csv(HEADER + body)
    try:
        tickets, findings = doctor.parse_csv(path, AS_OF)
        findings.extend(doctor.audit(tickets, AS_OF, **kwargs))
        return tickets, findings
    finally:
        os.unlink(path)


def rules(findings):
    """Return the set of rule names in a findings list."""
    return {item.rule for item in findings}


class TestParseTimestamp(unittest.TestCase):
    def test_iso_with_time(self):
        parsed = doctor.parse_timestamp("2026-11-17 10:00")
        self.assertEqual(parsed, datetime(2026, 11, 17, 10, 0,
                                         tzinfo=timezone.utc))

    def test_iso_with_z(self):
        parsed = doctor.parse_timestamp("2026-11-17T10:00:00Z")
        self.assertEqual(parsed, datetime(2026, 11, 17, 10, 0,
                                         tzinfo=timezone.utc))

    def test_date_only(self):
        parsed = doctor.parse_timestamp("2026-11-17")
        self.assertEqual(parsed, datetime(2026, 11, 17,
                                         tzinfo=timezone.utc))

    def test_day_month_year(self):
        parsed = doctor.parse_timestamp("17/11/2026 09:00")
        self.assertEqual(parsed, datetime(2026, 11, 17, 9, 0,
                                         tzinfo=timezone.utc))

    def test_bad_value(self):
        self.assertIsNone(doctor.parse_timestamp("not-a-date"))

    def test_empty_value(self):
        self.assertIsNone(doctor.parse_timestamp(""))
        self.assertIsNone(doctor.parse_timestamp(None))


class TestParseHelpers(unittest.TestCase):
    def test_parse_int(self):
        self.assertEqual(doctor.parse_int("12"), 12)
        self.assertEqual(doctor.parse_int(""), 0)
        self.assertEqual(doctor.parse_int("abc"), 0)
        self.assertEqual(doctor.parse_int("3.0"), 3)

    def test_parse_yes(self):
        self.assertTrue(doctor.parse_yes("yes"))
        self.assertTrue(doctor.parse_yes("TRUE"))
        self.assertTrue(doctor.parse_yes("1"))
        self.assertFalse(doctor.parse_yes("no"))
        self.assertFalse(doctor.parse_yes(""))
        self.assertFalse(doctor.parse_yes(None))

    def test_hours_between(self):
        start = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 11, 17, 14, 30, tzinfo=timezone.utc)
        self.assertEqual(doctor.hours_between(start, end), 5.5)
        self.assertIsNone(doctor.hours_between(None, end))
        self.assertIsNone(doctor.hours_between(start, None))

    def test_format_helpers(self):
        self.assertEqual(doctor.format_hours(2.5), "2.5 hours")
        self.assertEqual(doctor.format_hours(None), "n/a")
        self.assertEqual(doctor.format_rate(84.6), "84.6%")
        self.assertEqual(doctor.format_rate(None), "n/a")


class TestParseCsv(unittest.TestCase):
    def test_header_aliases(self):
        body = ("id,assignee,ticket_status,created,first_response,"
                "resolved_at,reply_count,reopen_count,escalated,"
                "satisfaction,source\n"
                "T-1,Ana,solved,2026-11-17 09:00,2026-11-17 09:30,"
                "2026-11-17 14:00,3,0,no,good,email\n")
        path = write_csv(body)
        try:
            tickets, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["agent"], "Ana")
        self.assertEqual(tickets[0]["csat"], "good")
        self.assertEqual(findings, [])

    def test_bom_header(self):
        path = write_csv("\ufeff" + HEADER + row())
        try:
            tickets, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(findings, [])

    def test_missing_agent_column(self):
        body = ("ticket_id,status,created_at\n"
                "T-1,solved,2026-11-17 09:00\n")
        path = write_csv(body)
        try:
            with self.assertRaises(ValueError):
                doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)

    def test_missing_created_column(self):
        body = ("ticket_id,agent,status\n"
                "T-1,Ana,solved\n")
        path = write_csv(body)
        try:
            with self.assertRaises(ValueError):
                doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)

    def test_empty_file(self):
        path = write_csv("")
        try:
            with self.assertRaises(ValueError):
                doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)

    def test_missing_file(self):
        with self.assertRaises(ValueError):
            doctor.parse_csv("/nonexistent/tickets.csv", AS_OF)

    def test_malformed_row_skipped(self):
        body = row() + "T-2,Ana,solved\n"
        tickets, findings = parse_and_audit(body)
        self.assertEqual(len(tickets), 1)
        self.assertIn("malformed-row", rules(findings))

    def test_blank_lines_skipped(self):
        body = row() + "\n" + row(ticket_id="T-2")
        tickets, findings = parse_and_audit(body)
        self.assertEqual(len(tickets), 2)
        self.assertEqual(findings, [])

    def test_duplicate_ticket_id(self):
        body = row() + row()
        tickets, findings = parse_and_audit(body)
        self.assertIn("duplicate-ticket-id", rules(findings))

    def test_missing_ticket_id(self):
        body = row(ticket_id="")
        tickets, findings = parse_and_audit(body)
        self.assertIn("missing-ticket-id", rules(findings))

    def test_missing_agent(self):
        body = row(agent="")
        tickets, findings = parse_and_audit(body)
        self.assertIn("missing-agent", rules(findings))

    def test_invalid_timestamp_created(self):
        body = row(created="not-a-date")
        tickets, findings = parse_and_audit(body)
        self.assertIn("invalid-timestamp", rules(findings))
        self.assertIsNone(tickets[0]["created"])

    def test_invalid_timestamp_first_reply(self):
        body = row(first_reply="not-a-date")
        tickets, findings = parse_and_audit(body)
        self.assertIn("invalid-timestamp", rules(findings))

    def test_future_timestamp(self):
        body = row(created="2026-12-01 09:00",
                   first_reply="2026-12-01 09:30",
                   solved="2026-12-01 10:00")
        tickets, findings = parse_and_audit(body)
        self.assertIn("future-timestamp", rules(findings))

    def test_invalid_status(self):
        body = row(status="weird")
        tickets, findings = parse_and_audit(body)
        self.assertIn("invalid-status", rules(findings))

    def test_invalid_csat(self):
        body = row(csat="weird")
        tickets, findings = parse_and_audit(body)
        self.assertIn("invalid-csat", rules(findings))

    def test_csat_none_is_clean(self):
        body = row(csat="none")
        tickets, findings = parse_and_audit(body)
        self.assertEqual(findings, [])

    def test_impossible_first_reply(self):
        body = row(created="2026-11-17 10:00",
                   first_reply="2026-11-17 09:00")
        tickets, findings = parse_and_audit(body)
        self.assertIn("impossible-dates", rules(findings))

    def test_impossible_solved(self):
        body = row(created="2026-11-17 09:00",
                   solved="2026-11-16 09:00")
        tickets, findings = parse_and_audit(body)
        self.assertIn("impossible-dates", rules(findings))

    def test_impossible_solved_before_reply(self):
        body = row(first_reply="2026-11-17 12:00",
                   solved="2026-11-17 11:00")
        tickets, findings = parse_and_audit(body)
        self.assertIn("impossible-dates", rules(findings))

    def test_extra_columns_ignored(self):
        body = HEADER.replace("\n", ",notes\n") + row()[:-1] + ",hi\n"
        path = write_csv(body)
        try:
            tickets, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(findings, [])


class TestFirstReply(unittest.TestCase):
    def test_slow_first_reply_is_error(self):
        body = row(first_reply="2026-11-17 15:00")
        tickets, findings = parse_and_audit(body)
        self.assertIn("slow-first-reply", rules(findings))
        item = [f for f in findings
                if f.rule == "slow-first-reply"][0]
        self.assertEqual(item.severity, "error")

    def test_fast_first_reply_clean(self):
        tickets, findings = parse_and_audit(row())
        self.assertEqual(findings, [])

    def test_first_reply_boundary(self):
        body = row(first_reply="2026-11-17 13:00")
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("slow-first-reply", rules(findings))

    def test_first_reply_flag(self):
        body = row(first_reply="2026-11-17 15:00")
        tickets, findings = parse_and_audit(
            body, max_first_reply_hours=8)
        self.assertNotIn("slow-first-reply", rules(findings))

    def test_no_first_reply_overdue(self):
        body = row(status="open", first_reply="", solved="")
        tickets, findings = parse_and_audit(body)
        self.assertIn("no-first-reply-overdue", rules(findings))
        item = [f for f in findings
                if f.rule == "no-first-reply-overdue"][0]
        self.assertEqual(item.severity, "error")

    def test_no_first_reply_fresh_is_clean(self):
        body = row(status="open", created="2026-11-17 22:00",
                   first_reply="", solved="")
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("no-first-reply-overdue", rules(findings))

    def test_no_first_reply_on_solved_not_flagged(self):
        body = row(status="solved", first_reply="", solved="")
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("no-first-reply-overdue", rules(findings))


class TestResolution(unittest.TestCase):
    def test_slow_resolution_is_error(self):
        body = row(solved="2026-11-19 10:00")
        tickets, findings = parse_and_audit(body)
        self.assertIn("slow-resolution", rules(findings))

    def test_fast_resolution_clean(self):
        tickets, findings = parse_and_audit(row())
        self.assertNotIn("slow-resolution", rules(findings))

    def test_resolution_boundary(self):
        body = row(created="2026-11-16 09:00",
                   first_reply="2026-11-16 09:30",
                   solved="2026-11-18 09:00")
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("slow-resolution", rules(findings))

    def test_open_ticket_has_no_resolution_check(self):
        body = row(status="open", first_reply="2026-11-17 09:30",
                   solved="")
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("slow-resolution", rules(findings))

    def test_negative_resolution_not_flagged(self):
        body = row(solved="2026-11-16 09:00")
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("slow-resolution", rules(findings))
        self.assertIn("impossible-dates", rules(findings))


class TestReopensAndEscalations(unittest.TestCase):
    def test_single_reopen_is_warning(self):
        body = row(reopens="1")
        tickets, findings = parse_and_audit(body)
        self.assertIn("reopened-ticket", rules(findings))
        item = [f for f in findings
                if f.rule == "reopened-ticket"][0]
        self.assertEqual(item.severity, "warning")

    def test_repeated_reopen_is_error(self):
        body = row(reopens="2")
        tickets, findings = parse_and_audit(body)
        self.assertIn("reopened-repeatedly", rules(findings))
        self.assertNotIn("reopened-ticket", rules(findings))
        item = [f for f in findings
                if f.rule == "reopened-repeatedly"][0]
        self.assertEqual(item.severity, "error")

    def test_escalated_is_warning(self):
        body = row(escalated="yes")
        tickets, findings = parse_and_audit(body)
        self.assertIn("escalated-ticket", rules(findings))

    def test_many_replies_is_warning(self):
        body = row(replies="12")
        tickets, findings = parse_and_audit(body)
        self.assertIn("many-replies", rules(findings))

    def test_replies_boundary(self):
        body = row(replies="10")
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("many-replies", rules(findings))

    def test_max_replies_flag(self):
        body = row(replies="12")
        tickets, findings = parse_and_audit(body, max_replies=15)
        self.assertNotIn("many-replies", rules(findings))


class TestAgentFindings(unittest.TestCase):
    _counter = 0

    def agent_body(self, agent, count, **overrides):
        body = ""
        for _ in range(count):
            TestAgentFindings._counter += 1
            params = {"ticket_id": "%s-%d" % (
                          agent, TestAgentFindings._counter),
                      "agent": agent}
            params.update(overrides)
            body += row(**params)
        return body

    def test_agent_overload(self):
        body = self.agent_body("Dan", 3, status="open",
                               first_reply="", solved="")
        tickets, findings = parse_and_audit(body, max_open=2)
        self.assertIn("agent-overload", rules(findings))
        item = [f for f in findings
                if f.rule == "agent-overload"][0]
        self.assertEqual(item.severity, "error")

    def test_agent_overload_counts_open_and_pending(self):
        body = (self.agent_body("Dan", 2, status="open",
                                first_reply="", solved="")
                + self.agent_body("Dan", 1, status="pending",
                                  first_reply="2026-11-17 09:30",
                                  solved=""))
        tickets, findings = parse_and_audit(body, max_open=2)
        self.assertIn("agent-overload", rules(findings))

    def test_agent_not_overloaded_at_limit(self):
        body = self.agent_body("Dan", 2, status="open",
                               first_reply="", solved="")
        tickets, findings = parse_and_audit(body, max_open=2)
        self.assertNotIn("agent-overload", rules(findings))

    def test_agent_slow_first_reply(self):
        body = self.agent_body("Ana", 2,
                               first_reply="2026-11-17 15:00")
        tickets, findings = parse_and_audit(body)
        self.assertIn("agent-slow-first-reply", rules(findings))

    def test_agent_fast_first_reply_clean(self):
        body = self.agent_body("Ana", 2)
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("agent-slow-first-reply", rules(findings))

    def test_agent_high_reopen_rate(self):
        body = (self.agent_body("Ben", 1, reopens="1")
                + self.agent_body("Ben", 3))
        tickets, findings = parse_and_audit(body)
        self.assertIn("agent-high-reopen-rate", rules(findings))

    def test_agent_low_reopen_rate_clean(self):
        body = self.agent_body("Ben", 4)
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("agent-high-reopen-rate", rules(findings))

    def test_agent_low_csat(self):
        body = (self.agent_body("Ben", 1, csat="bad")
                + self.agent_body("Ben", 2, csat="good"))
        tickets, findings = parse_and_audit(body)
        self.assertIn("agent-low-csat", rules(findings))

    def test_agent_low_csat_needs_minimum_rated(self):
        body = (self.agent_body("Ben", 1, csat="bad")
                + self.agent_body("Ben", 1, csat="good"))
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("agent-low-csat", rules(findings))

    def test_agent_high_csat_clean(self):
        body = self.agent_body("Ben", 3, csat="good")
        tickets, findings = parse_and_audit(body)
        self.assertNotIn("agent-low-csat", rules(findings))


class TestSummarize(unittest.TestCase):
    def test_summary_totals(self):
        body = (row(ticket_id="T-1", agent="Ana")
                + row(ticket_id="T-2", agent="Ben", status="open",
                      first_reply="", solved="", csat=""))
        path = write_csv(HEADER + body)
        try:
            tickets, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        findings.extend(doctor.audit(tickets, AS_OF))
        summary = doctor.summarize(tickets, findings, AS_OF)
        self.assertEqual(summary["tickets"], 2)
        self.assertEqual(summary["solved"], 1)
        self.assertEqual(summary["open"], 1)
        self.assertEqual(summary["agents"], 2)
        self.assertEqual(summary["average_first_reply_hours"], 0.5)
        self.assertEqual(summary["average_resolution_hours"], 5.0)
        self.assertEqual(summary["reopen_rate"], 0.0)
        self.assertEqual(summary["csat_good_rate"], 100.0)
        self.assertEqual(len(summary["per_agent"]), 2)
        self.assertEqual(summary["per_agent"][0]["agent"], "Ana")

    def test_empty_summary(self):
        summary = doctor.summarize([], [], AS_OF)
        self.assertEqual(summary["tickets"], 0)
        self.assertIsNone(summary["average_first_reply_hours"])
        self.assertIsNone(summary["average_resolution_hours"])
        self.assertIsNone(summary["csat_good_rate"])
        self.assertEqual(summary["per_agent"], [])

    def test_no_resolution_data(self):
        body = row(status="open", first_reply="2026-11-17 09:30",
                   solved="")
        path = write_csv(HEADER + body)
        try:
            tickets, findings = doctor.parse_csv(path, AS_OF)
        finally:
            os.unlink(path)
        summary = doctor.summarize(tickets, findings, AS_OF)
        self.assertIsNone(summary["average_resolution_hours"])
        self.assertEqual(
            summary["per_agent"][0]["average_resolution_hours"],
            None)


class TestOutput(unittest.TestCase):
    def test_text_output_sample(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "tickets.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18"])
        self.assertEqual(code, 0)
        self.assertIn("Tickets: 19, findings: 23, errors: 16, "
                      "warnings: 7", text)
        self.assertIn("Solved: 13, open: 6, agents: 4", text)
        self.assertIn("Average first reply: 2.0 hours, average "
                      "resolution: 10.1 hours", text)
        self.assertIn("Ben: 4 tickets, 3 solved, 1 open, first "
                      "reply 0.6 hours, resolution 24.7 hours, "
                      "reopen 25.0%, escalation 0.0%, "
                      "CSAT 33.3%", text)
        self.assertIn("Dan: 5 tickets, 1 solved, 4 open, first "
                      "reply 0.2 hours, resolution n/a, reopen "
                      "0.0%, escalation 0.0%, CSAT 100.0%", text)

    def test_json_output(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "warnings-only.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--json"])
        self.assertEqual(code, 0)
        report = json.loads(text)
        self.assertEqual(report["tickets"], 3)
        self.assertEqual(report["errors"], 0)
        self.assertEqual(report["warnings"], 3)
        self.assertEqual(len(report["findings"]), 3)

    def test_clean_output(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18"])
        self.assertEqual(code, 0)
        self.assertIn("All tickets clean.", text)

    def test_out_file(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        with tempfile.TemporaryDirectory() as directory:
            out_path = os.path.join(directory, "report.txt")
            code, text = run_cli([path, "--as-of", "2026-11-18",
                                  "--out", out_path])
            self.assertEqual(code, 0)
            self.assertEqual(text, "")
            with open(out_path, encoding="utf-8") as handle:
                self.assertIn("All tickets clean.", handle.read())

    def test_check_exit_codes(self):
        directory = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        sample = os.path.join(directory, "examples", "tickets.csv")
        clean = os.path.join(directory, "examples", "clean.csv")
        warnings_only = os.path.join(
            directory, "examples", "warnings-only.csv")
        code, _ = run_cli([sample, "--as-of", "2026-11-18",
                           "--check"])
        self.assertEqual(code, 1)
        code, _ = run_cli([clean, "--as-of", "2026-11-18",
                           "--check"])
        self.assertEqual(code, 0)
        code, _ = run_cli([warnings_only, "--as-of", "2026-11-18",
                           "--check"])
        self.assertEqual(code, 0)
        code, _ = run_cli([warnings_only, "--as-of", "2026-11-18",
                           "--check", "--strict"])
        self.assertEqual(code, 1)

    def test_bad_flag_values(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "clean.csv")
        code, _ = run_cli([path, "--max-first-reply-hours", "-1"])
        self.assertEqual(code, 2)
        code, _ = run_cli([path, "--max-reopen-rate", "101"])
        self.assertEqual(code, 2)
        code, _ = run_cli([path, "--min-csat", "101"])
        self.assertEqual(code, 2)
        code, _ = run_cli([path, "--as-of", "not-a-date"])
        self.assertEqual(code, 2)

    def test_max_open_flag(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))),
            "examples", "tickets.csv")
        code, text = run_cli([path, "--as-of", "2026-11-18",
                              "--max-open", "2"])
        self.assertEqual(code, 0)
        self.assertIn("findings: 24", text)
        self.assertIn("agent Dan: agent has 4 open tickets",
                      text)

    def test_version(self):
        self.assertEqual(doctor.__version__, "1.0.0")


if __name__ == "__main__":
    unittest.main()
