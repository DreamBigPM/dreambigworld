# Blueprint 04 — Vacancy Tracker

**The problem:** Every day a unit sits empty, you lose money. But more than that —
you lose track. How long has it been vacant? How many people have you shown it to?
Where did that one interested applicant go? You're managing the pipeline in your head
and it's leaking.

**What this builds:** A vacancy dashboard showing every empty unit, how many days
it's been on the market, every showing you've done, and where each applicant stands
in your pipeline — from first contact to move-in.

**Time to build:** 1–2 hours

**What to have ready:** Your current vacant units (address, bed/bath, asking rent)
and any showings or applicants you already have in the pipeline — even rough notes.

---

## Hand This to Jarvis

*Open Claude Code. Copy everything below the line. Paste it. Hit enter.*

---

I want to build a vacancy tracker for my property management business.

Here's the problem: vacant units cost me money every single day. I need to
know exactly which units are empty, how long they've been sitting, who I've
shown them to, and where each prospect is in the process. Right now that
information lives in my head and in scattered texts.

Here's exactly what I want it to do:

1. Show me all my currently vacant units, sorted by how long they've been empty —
   longest first. I want to feel the urgency of every empty day.
   Each unit should show: address, unit number, bed/bath, asking rent, days vacant

2. For each unit, let me log showings: who came, when, and a quick note on how it went

3. Track each applicant through a simple pipeline:
   Shown → Applied → Under Review → Approved → Denied → Moved In

4. Let me mark a unit as filled — which should log the move-in date and
   calculate how many days it was vacant total

I don't need this connected to my PM software right now. I just need one clear
place to see what's happening with my pipeline.

Please follow the normal build process: tell me what you're going to build
before you write anything. I want to approve the plan first.

---

## After the Build

Check this every morning:
- Which unit has been vacant the longest? Make one call about it today.
- Any applicants you haven't followed up with in 48 hours?
- Any showings scheduled this week?

**Result:** You will always know exactly where every vacancy stands.
No more pipeline disappearing into your inbox.
