# Personal proxy: launcher mode and orb progress

Origin: story v2.1.0 task 9b, owner decisions of 2026-10-22.

1. Launcher mode. `launcher/runtime.py` offers only "assistant" and "mcp", so the tray
   launcher cannot start `--personal-proxy`, and a startup failure before the window opens
   (exit code 5) is invisible from it. Add a menu entry for the mode and make its startup
   failure visible. Needs its own card and a human check of the launcher.
2. Orb progress. In the proxy mode the orb shows Ready or Listening during a 10-30 s
   request, because `RuntimeStateTracker` follows turn events this mode never emits. Postponed
   by the owner; a tracker event from the service would fix it.
