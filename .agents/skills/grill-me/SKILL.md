---
name: grill-me
description: Stress-test a relay plan, spec, issue or idea by interrogating it one question at a time — walking the decision tree, resolving dependencies, surfacing every unstated assumption until you and the user share one model. Use when the user says "grill me", "poke holes in this", "stress-test this", "what am I missing".
argument-hint: the idea to grill, or a path to a brainstorm / spec / plan, or an issue number
---

# Grill Me

Honour `.agents/skills/README.md`. You are the skeptic. Interrogate until every decision is deliberate. Position: between deciding *what* and formalising it (`/brainstorm → **/grill-me** → /to-spec`); also valid against a finished plan before `/implement`, or against a GitHub issue picked up cold.

## The method — one question at a time
1. **Ask ONE question, then stop.** Never a numbered list.
2. **Look before you ask.** Read the code, the README, the brainstorm, and hisab's transport files when the question is about WhatsApp. Interrogate decisions, not facts.
3. **Offer a recommended answer with each question.** "I'd lean toward Y because Z — agree?"
4. **Walk the tree.** Root decision first; follow each branch to the end before backing out.
5. **Stop when the design holds**, not when you run out of questions.
6. **Write back.** Record each settled answer in the artifact you were pointed at as you go, so a context clear loses nothing.

## Relay pressure points
- **The write boundary.** Can the agent write anywhere the config does not name? Is a new folder denied by default? What if the folder's own agent settings allow more — do the relay's denies still win?
- **Session control.** Does reset mint a new session without a model call? Does the model choice survive a reset? What happens when a resume fails?
- **Transport.** Dedup by message id? Offset advanced only after the batch? 429, 503, 409, a dead token, a dropped connection, a 4,096-char reply, a batch of five messages while the agent is still thinking?
- **The agent adapter.** Is every text block of the reply kept, not only the last? Is the child's stdin closed so it cannot swallow the batch? Is Codex a second adapter behind the same seam, or a fork of the code?
- **Media and voice.** Image, document, voice note: fetched, handed by path, cleaned up? A failed transcription reported, never passed on?
- **Errors on the phone.** What does the user see when the agent crashes — raw stderr, or a sentence? Could that text carry a path or a secret?
- **Privacy.** Anything that would carry the author's server, token, creator id, folder or skill names into the repo, an issue or a doc?
- **Verification seam.** Which check proves this without a network, and which needs a phone?
- **YAGNI.** What here is not needed for the first release?

## When done
Summarise in a few lines: decisions locked, assumptions made explicit, risks accepted on purpose. Hand off: `/to-spec` (usual), `/refine-approach` to write it back into a doc, `/create-plan` for small work.

## What NOT to do
- More than one question at a time. Asking what you could look up. Implementing before the user confirms. Softening. Reopening a decision the artifact records as already made.
