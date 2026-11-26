# Good first issues

Seeded issues for new contributors. File each one on GitHub with
the `good first issue` and `help wanted` labels.

## 1. Add a tickets-needing-attention table

Title: Show the breaching tickets first, oldest first

Description: After the per-agent summary, print a short table
of the tickets that need attention today (slow first reply,
no first reply overdue, slow resolution, reopened
repeatedly), sorted oldest first (ticket id, agent, rule,
hours waiting), so a team lead can work the queue
top-down without reading every finding. Tickets with no
created date go last.

Difficulty: Easy

Acceptance criteria: the table appears in text output with
the correct order for the sample file (T-106 first, created
2026-11-13, then T-103, then T-108, then T-102 and T-104,
then T-117); JSON output is unchanged; a test checks the
table rows.

## 2. Add a configurable minimum rated tickets threshold

Title: Let the CSAT minimum rated count be configurable

Description: Add a --min-rated-tickets flag that sets how
many rated tickets an agent needs before the low CSAT flag
applies. The default stays at three.

Difficulty: Easy

Acceptance criteria: Ben is flagged for low CSAT when
--min-rated-tickets 2 is passed on a file where he has
only 2 rated tickets, and is not flagged without the flag;
a test covers both cases; README documents the flag.

## 3. Report the slowest agent in the summary

Title: Print the agent with the slowest average first reply

Description: Add one line to the text summary naming the
agent with the slowest average first reply time (agent,
average hours, ticket count), so a team lead can see the
biggest coaching need at a glance. When no agent has a
first reply time recorded, the line is omitted.

Difficulty: Easy

Acceptance criteria: the line appears for the sample file
naming Ana at 5.6 hours; it is absent for a file where no
ticket has a first reply date; JSON output is unchanged;
a test checks both cases.

## 4. Split the per-agent table by channel

Title: Add a per-channel breakdown to the per-agent table

Description: Add the channel split to each per-agent
summary line: the ticket count followed by the counts per
channel, for example "Ana: 6 tickets (email 4, chat 2)".
The channel column already parses, so no input change is
needed. Tickets with an empty channel count as
"(no channel)".

Difficulty: Easy

Acceptance criteria: the sample file shows Ana with 6
tickets (email 4, chat 2) and Ben with 4 tickets (email 3,
chat 1); JSON per-agent rows gain a channels field with
the same counts; a test checks both.
