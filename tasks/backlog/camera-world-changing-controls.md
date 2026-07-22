# Backlog note: camera controls that change the world

**Status:** Backlog. Not a v1.6.2 task card - v1.6.2 reads frames only.
**Decision recorded:** `PROJECT.md`, 2026-07-22.
**Hardware:** Imou Ranger Dual (IPC-S2XP-6M0WED). Channel 1 is the upper
lens, motorized on two axes. Channel 2 is the fixed wide lens and carries
an illuminator.

## What this is about

The verified LAN camera offers two controls that are not reads: pan/tilt
on the motorized lens, and the wide lens's illuminator. Both are useful -
a model that knows it can aim the detail lens can finish a task it would
otherwise fail, and light makes a dark room legible. Neither is planned
now, and neither should arrive by accident inside a capture task.

Naming it precisely, because an earlier framing got this wrong: steering
the lens is not Jarvis acting on its own initiative. It would happen while
carrying out the user's own request, as an extended operation within a
task. The reason it still needs its own gate is different:

- **Scope of consent.** "Look at the camera" agrees to the view currently
  framed. A steerable lens turns "look around the room" into a survey of
  corners the user never aimed at. Where the lens points is precisely what
  anchors a person's sense of what the camera can see, and moving it
  removes that anchor.
- **Irreversible physical state.** The lens stays where Jarvis left it
  after the task ends, changing the next capture and the owner's own use
  of the camera. The illuminator is the same shape of act: switching it on
  puts light into a real room, possibly with people in it. These are the
  product's first tools that change the world instead of reading it.

The general principle worth keeping past this camera: world-changing tools
are separated from reading tools by default, whatever the individual
operation costs.

## Shape when it is built

- A permission distinct from the camera on/off switch. The camera being
  enabled means Jarvis may look; it must not imply Jarvis may aim or
  illuminate. Off by default, enabled by explicit user action, and
  non-delegable like every other privacy control.
- The source registry describes each source honestly, including that the
  motorized lens shows wherever it was last aimed - by a previous task, by
  the owner, or by the camera's own auto-tracking - so a capture from it
  is not reproducible.
- Any movement is audited as its own event, not folded into the capture
  that followed it. A user reviewing what happened should see that the
  camera was aimed, not only that a frame was taken.

## Open questions for whoever picks this up

- Does the model get to aim, or does aiming stay a user action with the
  model limited to asking for it? These differ in how much a prompt
  injection through observed content can accomplish.
- Is auto-tracking left on? It moves the lens with no tool call at all,
  which makes "where is it pointing" unanswerable from Jarvis's own
  records.
- Does returning the lens to a home position after a task belong here, and
  does that make the irreversibility argument weaker or just quieter?
