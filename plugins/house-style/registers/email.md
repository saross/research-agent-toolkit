---
name: register-email-default
description: >-
  Generic email register bundled with the house-style plugin: the shape, the
  three-way hedge test, recipient tiers, mechanics, and exit checks for
  drafts that the sender revises before sending. Used by the draft-email
  skill when the user has set no register of their own.
---

# Email register (bundled default)

**Load with this file:** `anti-tic.md`, in the same folder.

**What this is.** A starting register for drafting email on someone's
behalf, used when they have not set one of their own. It was distilled
from one sender's register, which was derived from their sent mail and
recalibrated three times by comparing drafts with what they actually
sent. The personal detail (names, sign-offs, quoted messages) is gone;
the examples below are made up. A register of your own should replace
the sign-offs, tiers, and examples with yours: copy this file, edit it,
and point the plugin's `email_register` option at your copy.

**This is a register for drafts.** The sender revises every email
before sending, so the register aims at a good core, not a finished
message.

## The shape: warm at the edges, precise in the middle

Keep the greeting and the close human. Let the ask itself be a clean
question with nothing wrapped round it. Warmth is not decoration: it is
part of why people reply quickly. **The failure mode of this register
is brusqueness**, which costs more than hedging does.

## Rule 1: draft at the floor of the range, not the average

**Adding warmth on review takes ten seconds. Removing hedges and
justification takes minutes**, because each one has to be found, judged,
and cut with the sentence rebuilt round it. So draft closer to the
tightest message the sender would write than to their median one. They
add back whatever the relationship needs.

## Rule 2: the three-way hedge test

Before cutting a hedge, ask what it buys.

| Kind | Test | Verdict |
| --- | --- | --- |
| **Epistemic**: marks real uncertainty | Would removing it make the sentence less true? | **Keep** |
| **Cost-of-no**: makes refusal cheap for the recipient | Is the recipient being asked for something they can legitimately refuse? | **Keep** ("Could we use your logo on the page? If not, that's fine.") |
| **Status-lowering**: discounts the sender or their work | Does it protect the recipient, or only pre-empt the sender's embarrassment? | **Cut** |

**In one line: keep the hedges that protect the other person; cut the
ones that discount the sender.** Patterns to cut: discounting one's own
work ("a fairly thorough (I think) survey"); pre-criticising an
attachment; self-diagnosing as unreasonable ("just being a little
paranoid"); downgrading one's contribution ("two things that might
feed in"); and the reflex apology for delay. Apologise when a delay
actually cost someone something; otherwise just answer.

## Rule 3: three recipient tiers

Kept deliberately coarse.

| Tier | Who | Hedging |
| --- | --- | --- |
| **Asking a favour they may refuse** | External partners, new contacts, anyone whose "no" is legitimate | Keep the cost-of-no hedges, and offer the exit in the same breath as the ask |
| **Already opted in** | Collaborators, co-chairs, colleagues already committed | Drop the cost-of-no hedges. A clean question respects their time; softening at someone who already said yes reads as not having noticed |
| **Transactional** | Service providers, support desks, organisers | Answer, confirm, stop. No apology unless the delay cost them |

## Mechanics

- **Contractions throughout**: "we're", "I'd", "isn't". A formal draft
  is the model's register, not the sender's.
- **No em-dashes.** Type `--` where a dash is needed.
- **Asks are questions** with question marks, not statements of desire.
  Yes: "Can we mention the project by name?" No: "I would like to
  mention the project, if you are comfortable with that."
- **Reasons ride inside clauses**, not in sentences of their own ("We're
  redesigning the website, where we hope to show this work.").
- **Bullets for several items**, short, with no sub-bullets.
- **Closes hand over control** ("Let me know how you'd like to
  proceed.").
- **Greeting and sign-off** follow the sender's own habits, which a
  personal register records. Without one, use "Hi Name," for a
  colleague, "Dear Name," for a first contact or a favour, and the
  sender's first name to sign.
- **Parenthetical asides** are fine when they add information; cut the
  ones that add doubt about the sender.

## Rule 4: concise is the default, not an instruction

A draft should need no "be concise" prompt. One idea per sentence, no
clause that restates or justifies the sentence it hangs off, and the
whole message at the length the recipient needs to act, not the length
that shows the work behind it.

## Rule 5: state the fact and stop

Cut the clause that explains why the fact just stated matters. If the
recipient can draw the inference, don't draw it for them. Trailing
"so…", "which…", and "and it is…" clauses are the signature.

## Rule 6: never remind someone of what they already agreed

No "As promised" and no "on the basis you already agreed". Don't restate
context the recipient supplied or was party to.

## Rule 7: no signposting the reader can see

"Two questions." before two questions is filler. Bullets and paragraph
breaks are the signposts.

## Rule 8: decide, then offer a look, rather than ask

If the sender can answer a question themselves, the draft answers it and
offers the recipient a chance to review. Questions go to the recipient
only when the answer is genuinely theirs.

## Rule 9: the call to action sits near the end

When something is needed, the last substantive paragraph says what,
from whom, and by when if a date exists. The ask may also appear early;
the closing one is what the recipient acts on after reading.

## Rule 10: the draft goes light on warmth

The draft carries the warm edges (greeting, close) and credits people
by name where credit is due, which is information, not tone. It adds no
exclamation marks or repeated thanks: the sender modulates those to the
recipient. Don't pad a draft with warmth to make up for cutting
justification.

## Rule 11: after a meeting, open on the meeting, not the shortfall

"It was good to see you at the conference, and I'm sorry we ran out of
time." Any shortfall comes second, or not at all.

## Rule 12: regret for a shared miss is not a reflex apology

"We ran out of time" is something both people lost, and saying so is
warmth. It stays.

## Rule 13: on the favour tier, offer the call

"Would you like a call about X?", with no stated length. Those already
opted in can still get "Could we catch up?".

## Rule 14: no pitch or paperwork before they've shown interest

A follow-up asks about the recipient's situation. It doesn't promise a
demonstration, name contract documents, or raise procurement until they
ask. A spoken yes is not treated as settled in writing.

## Rule 15: say what oral conversation you're picking up

After a busy event the recipient may not recall it, so one clause names
it, hedged if unsure ("I believe you mentioned that…"). This qualifies
Rule 6, which holds for what someone agreed in writing.

## Rule 16: say who a colleague is at first mention

"Sam Lee (copied), our technical lead."

## Rule 17: leave a slot for what is the sender's to settle

Where a message depends on commercial terms, personal circumstances, or
a view of a named person, ask the sender first or write `[Sender: ...]`.
Don't draft around the gap.

## Rule 18: cold contacts get a human reason and an opt-out

At first contact, one clause of why ("because your work on X seems so
close to ours") earns its place. Keep a soft opt-out ("If not, no
problem, and I won't write again.").

## Exit checks before handing over a draft

1. **Where is the ask?** If it isn't in the first three sentences of
   its paragraph, move it.
2. **Is the ask a question?** If it is a statement of desire, rewrite
   it.
3. **Every hedge through Rule 2.** Epistemic and cost-of-no stay;
   status-lowering goes.
4. **Any apology?** Did the thing apologised for cost the recipient
   something? If not, cut it. Regret for a shared miss stays (Rule 12).
5. **Contractions present?**
6. **Could the recipient act without re-reading**, and without
   remembering a conversation the draft doesn't name?
7. **Are the edges warm?** If the whole thing reads clipped, the
   correction has overshot.
8. **Clause sweep.** Read each sentence to its final comma; cut anything
   after it that explains, justifies, or restates (Rule 5).
9. **Agreement echo.** Any "as promised", "as agreed", or "as
   discussed"? Cut it (Rule 6).
10. **Call to action.** If something is needed, is it plain in the last
    substantive paragraph (Rule 9)?
11. **Warmth.** Edges warm, names not descriptions, and no more (Rule
    10).
12. **Dash check.** No em-dashes.
13. **Opener.** After a meeting, does the first line lead with the
    meeting (Rule 11)?
14. **Favour-tier ask.** "Would you like", with no stated length (Rule
    13)?
15. **Pitch sweep.** Any demonstration, contract, or procurement they
    haven't asked for? Cut it (Rule 14).
16. **Gaps.** Did the draft smooth over something only the sender can
    settle? Make it a slot (Rule 17).
