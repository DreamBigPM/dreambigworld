# Blueprint 03 — Maintenance Request Log

**The problem:** A tenant texts you about a leak. You mean to call the plumber.
Three days go by. Now the tenant is angry and the ceiling is worse. Or an owner
asks what you've spent on their property this year and you have to go digging
through emails and texts to piece it together.

**What this builds:** A maintenance log where you capture every request the moment
it comes in, assign it to a vendor, track its status, log the cost when it's done,
and pull a full history for any property in 30 seconds.

**Time to build:** 1–2 hours

**What to have ready:** A list of your current open requests (rough notes are fine)
and your main vendors — plumber, electrician, handyman — with their contact info.

---

## Hand This to Jarvis

*Open Claude Code. Copy everything below the line. Paste it. Hit enter.*

---

I want to build a maintenance request log for my property management business.

Here's the problem: requests come in from multiple directions — text, email,
voicemail. I deal with some immediately and forget others. I can never tell an
owner exactly what's been done on their property or what it cost.

Here's exactly what I want it to do:

1. Let me add a new request quickly — I want this to take under 30 seconds.
   I need to capture: tenant name, unit, what the problem is, when I received it,
   and which vendor I'm assigning it to
2. Track the status of each request: Open, In Progress, or Completed
3. When work is done, let me add a completion note and the final cost
4. Let me filter by property so I can pull everything that's happened at
   one address — useful when an owner asks questions

Later I'll want to generate a maintenance section for my monthly owner reports,
but don't build that yet. Just build the log first. Simple and fast.

Please follow the normal build process: tell me what you're going to build
before you write anything. I want to approve the plan first.

---

## After the Build

Every time a request comes in:
- Open the log, add it in 30 seconds
- Assign the vendor
- Update the status when work is scheduled and again when it's done
- Log the final cost

**Result:** Nothing falls through the cracks. You can answer any owner's
question about their property in under a minute.
