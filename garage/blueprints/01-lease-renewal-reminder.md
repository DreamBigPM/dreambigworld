# Blueprint 01 — Lease Renewal Reminder

**The problem:** You find out a lease expires in two weeks. The tenant is surprised.
You're scrambling. The unit might go vacant. You lose a month of rent — minimum.

**What this builds:** A tool that shows you every lease expiring in the next 60 days,
sorted soonest first, with a 60-day and 30-day reminder email drafted for each tenant
and ready to send.

**Time to build:** 1–2 hours

**What to have ready:** Your tenant names, unit numbers, and lease end dates.
(A rough spreadsheet or even a handwritten list is fine — you'll enter it during the build.)

---

## Hand This to Jarvis

*Open Claude Code. Copy everything below the line. Paste it. Hit enter.*

---

I want to build a lease renewal reminder tool for my property management business.

Here's the problem I'm solving: I manage multiple units and I keep getting caught
off guard when leases expire. By the time I realize one is coming up, I've already
lost the window for a smooth renewal conversation. I want to fix that permanently.

Here's exactly what I want it to do:

1. Let me enter or update my tenant list: name, unit number, and lease end date
2. Show me every lease expiring in the next 60 days, sorted soonest first
3. For each expiring lease, have two emails already drafted — one for the 60-day
   outreach and one for the 30-day reminder — that I can copy and send without editing

The emails should sound like they came from a real property manager, not a robot.
Warm but professional. I'll personalize them slightly before sending.

I don't want it to send emails automatically. I just want the draft ready so
I can review and send it myself in under two minutes.

Keep it simple. I want to be able to run this at the start of each week and
be done in under five minutes.

Please follow the normal build process: tell me what you're going to build
before you write anything. I want to approve the plan first.

---

## After the Build

Run this every Monday morning. Takes about two minutes:
- Scan the list for anything expiring in the next 60 days
- Copy the draft email
- Send it — or schedule it for later that day

**Result:** You will never be surprised by an expiring lease again.
