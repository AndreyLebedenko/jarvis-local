// Generic keyboard-interaction primitives for the Status Console
// (task-ui-ux-1). Pure DOM helpers: no knowledge of app.js's control-
// sending functions, no uiString() calls, no engine state. app.js wires
// these to the concrete toggle groups and item lists; that keeps the
// generic behavior testable/reasoned about on its own and keeps every
// localized string in the one place strings.js's contract already covers.

// ---------------------------------------------------------------------
// Radio groups (view / visibility / reasoning-level toggles)
// ---------------------------------------------------------------------
//
// A radio button's own onclick attribute (already wired to
// setActiveView()/setVisibilityMode()/setReasoningLevel()) stays the one
// place a selection is actually requested. Arrow-key navigation here only
// moves focus and re-fires that same click - a keyboard user never sees a
// selection app.js itself did not also see from a real click, preserving
// the existing "engine confirms, UI never guesses" invariant for the
// visibility/reasoning groups (see app.js's header comment).

function _radioButtons(container) {
  return Array.from(container.querySelectorAll('[role="radio"]'));
}

function initRadioGroup(container) {
  if (!container || container.dataset.radiogroupBound === "true") return;
  container.dataset.radiogroupBound = "true";
  container.addEventListener("keydown", (event) => _onRadioGroupKeydown(event, container));
}

function _onRadioGroupKeydown(event, container) {
  const buttons = _radioButtons(container);
  if (buttons.length === 0 || event.target !== document.activeElement) return;
  const currentIndex = Math.max(0, buttons.indexOf(document.activeElement));
  let targetIndex;
  switch (event.key) {
    case "ArrowRight":
    case "ArrowDown":
      targetIndex = (currentIndex + 1) % buttons.length;
      break;
    case "ArrowLeft":
    case "ArrowUp":
      targetIndex = (currentIndex - 1 + buttons.length) % buttons.length;
      break;
    case "Home":
      targetIndex = 0;
      break;
    case "End":
      targetIndex = buttons.length - 1;
      break;
    default:
      return;
  }
  event.preventDefault();
  buttons[targetIndex].focus();
  buttons[targetIndex].click();
}

// Reads a group's authoritative .sel state (already the single source of
// truth applyThinkingMode()/applyVisibilityMode()/setActiveView() maintain)
// back into aria-checked and roving tabindex. Never invents a selection
// those functions did not also set - call this from inside them, right
// after their existing .sel loop, not instead of it.
function syncRadioGroup(container) {
  if (!container) return;
  const buttons = _radioButtons(container);
  let checkedButton = null;
  for (const button of buttons) {
    const checked = button.classList.contains("sel");
    button.setAttribute("aria-checked", String(checked));
    if (checked) checkedButton = button;
  }
  const current = checkedButton || buttons[0];
  for (const button of buttons) {
    button.tabIndex = button === current ? 0 : -1;
  }
}

// ---------------------------------------------------------------------
// Roving-tabindex item lists (Journal sessions, tool rows, memory files,
// annotations)
// ---------------------------------------------------------------------
//
// Key handling only ever fires when the roving item ITSELF is the event
// target - never when focus has moved on into one of its own native
// controls (a checkbox, a button, a textarea). That is what lets one
// generic helper wrap wildly different item shapes (a plain selectable
// row, a checkbox row, a rich editable panel) without reimplementing or
// double-firing whatever those native controls already do correctly on
// their own: a checkbox already toggles on Space, a textarea already
// needs every arrow key for caret movement.

const _F2_EDITABLE_SELECTOR = "textarea, input:not([type='checkbox']):not([type='radio'])";
const _TYPEAHEAD_TIMEOUT_MS = 600;
const _typeaheadState = new WeakMap();

function _rovingItems(container, itemSelector) {
  return Array.from(container.querySelectorAll(itemSelector));
}

// Re-establishes roving tabindex after a list is rebuilt (every caller
// here rebuilds via replaceChildren() + re-append). `isCurrent(item)` picks
// which item becomes the Tab stop (e.g. the selected session); omitted, the
// first item is used - a reasonable, deterministic default since a fresh
// rebuild has no prior element identity to preserve.
function refreshRovingList(container, itemSelector, isCurrent) {
  if (!container) return;
  const items = _rovingItems(container, itemSelector);
  if (items.length === 0) return;
  const current = (isCurrent && items.find(isCurrent)) || items[0];
  for (const item of items) item.tabIndex = item === current ? 0 : -1;
}

// handlers: { onActivate(item), onToggle(item), getLabel(item) }. onToggle
// falls back to onActivate when absent (a plain selectable row has no
// separate "toggle" concept from "activate"). getLabel enables typeahead;
// omitted, typeahead is inert.
function initRovingList(container, itemSelector, handlers = {}, isCurrent) {
  if (!container) return;
  if (container.dataset.rovingBound !== "true") {
    container.dataset.rovingBound = "true";
    container.addEventListener("keydown", (event) =>
      _onRovingListKeydown(event, container, itemSelector, handlers)
    );
  }
  refreshRovingList(container, itemSelector, isCurrent);
}

function _onRovingListKeydown(event, container, itemSelector, handlers) {
  const item = event.target.closest(itemSelector);
  if (!item || event.target !== item) return;
  const items = _rovingItems(container, itemSelector);
  const currentIndex = items.indexOf(item);
  if (currentIndex === -1) return;

  const focusItem = (index) => {
    items.forEach((candidate, i) => { candidate.tabIndex = i === index ? 0 : -1; });
    items[index].focus();
  };

  switch (event.key) {
    case "ArrowDown":
    case "ArrowRight":
      event.preventDefault();
      focusItem((currentIndex + 1) % items.length);
      return;
    case "ArrowUp":
    case "ArrowLeft":
      event.preventDefault();
      focusItem((currentIndex - 1 + items.length) % items.length);
      return;
    case "Home":
      event.preventDefault();
      focusItem(0);
      return;
    case "End":
      event.preventDefault();
      focusItem(items.length - 1);
      return;
    case " ":
      event.preventDefault();
      (handlers.onToggle || handlers.onActivate)?.(item);
      return;
    case "Enter":
      handlers.onActivate?.(item);
      return;
    case "F2":
      _focusF2Editable(event, item);
      return;
    default:
      _handleTypeahead(event, container, item, items, focusItem, handlers.getLabel);
  }
}

function _focusF2Editable(event, item) {
  const editable = item.querySelector(_F2_EDITABLE_SELECTOR);
  if (!editable) return; // no-op on items with nothing editable (e.g. a session row)
  event.preventDefault();
  editable.focus();
  if (typeof editable.select === "function") editable.select();
}

function _handleTypeahead(event, container, item, items, focusItem, getLabel) {
  if (!getLabel || event.key.length !== 1) return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const now = Date.now();
  const previous = _typeaheadState.get(container);
  const buffer = previous && now - previous.time <= _TYPEAHEAD_TIMEOUT_MS ? previous.text : "";
  const nextBuffer = (buffer + event.key).toLowerCase();
  _typeaheadState.set(container, { text: nextBuffer, time: now });
  const currentIndex = items.indexOf(item);
  const ordered = [...items.slice(currentIndex + 1), ...items.slice(0, currentIndex + 1)];
  const match = ordered.find((candidate) =>
    (getLabel(candidate) || "").toLowerCase().startsWith(nextBuffer)
  );
  if (match) {
    event.preventDefault();
    focusItem(items.indexOf(match));
  }
}

// Standalone F2 affordance for a focusable item that is not part of a
// roving list (a Journal transcript panel: one per voice message, scattered
// through the feed, never siblings to arrow-navigate between). Mirrors
// initRovingList()'s F2/Escape pair without the arrow/Home/End/typeahead
// machinery a real list needs.
function enableStandaloneF2Edit(item) {
  if (!item || item.dataset.f2Bound === "true") return;
  item.dataset.f2Bound = "true";
  if (!(item.tabIndex >= 0)) item.tabIndex = 0;
  item.addEventListener("keydown", (event) => {
    if (event.target !== item) {
      if (event.key === "Escape" && event.target.matches(_F2_EDITABLE_SELECTOR)) {
        event.preventDefault();
        item.focus();
      }
      return;
    }
    if (event.key === "F2") _focusF2Editable(event, item);
  });
}

// ---------------------------------------------------------------------
// Context menu (task-ui-ux-2): one reusable role="menu" popup, reachable
// by right-click, Shift+F10, and a visible per-item menu button. Every
// item type (Journal session, feed message, tool row) supplies only a
// list of already-existing actions; this module owns positioning,
// open/close, and roving arrow-key navigation between menu items.
// ---------------------------------------------------------------------

let _contextMenuEl = null;
let _contextMenuReturnFocus = null;
let _contextMenuOutsideHandler = null;

function _contextMenuOpen() {
  return _contextMenuEl !== null;
}

function _closeContextMenu() {
  if (!_contextMenuEl) return;
  _contextMenuEl.remove();
  _contextMenuEl = null;
  if (_contextMenuOutsideHandler) {
    document.removeEventListener("click", _contextMenuOutsideHandler);
    _contextMenuOutsideHandler = null;
  }
  _contextMenuReturnFocus?.focus?.();
  _contextMenuReturnFocus = null;
}

// anchor is either an {x, y} pointer position (right-click) or an Element
// to position just below (Shift+F10 / the visible menu button, so it is
// reachable and positioned sensibly without a pointer).
function _positionContextMenu(menu, anchor) {
  const rect = anchor instanceof Element ? anchor.getBoundingClientRect() : null;
  const x = rect ? rect.left : anchor.x;
  const y = rect ? rect.bottom + 2 : anchor.y;
  const maxX = Math.max(4, window.innerWidth - menu.offsetWidth - 8);
  const maxY = Math.max(4, window.innerHeight - menu.offsetHeight - 8);
  menu.style.left = `${Math.min(x, maxX)}px`;
  menu.style.top = `${Math.min(y, maxY)}px`;
}

// entries: [{ label, run, disabled? }, ...]; falsy entries are dropped, so
// a caller can inline a condition (e.g. `session.id !== activeId &&
// {...}`) instead of building an array by hand. Only one menu is ever
// open - opening a new one always closes whatever was open first.
function openContextMenu(entries, anchor, returnFocusTo) {
  _closeContextMenu();
  const visible = entries.filter(Boolean);
  if (visible.length === 0) return;
  _contextMenuReturnFocus = returnFocusTo || document.activeElement;

  const menu = document.createElement("div");
  menu.className = "context-menu";
  menu.setAttribute("role", "menu");

  const items = visible.map((entry) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "context-menu-item";
    item.setAttribute("role", "menuitem");
    item.tabIndex = -1;
    item.textContent = entry.label;
    if (entry.disabled) {
      item.disabled = true;
      item.setAttribute("aria-disabled", "true");
    } else {
      item.addEventListener("click", () => {
        _closeContextMenu();
        entry.run();
      });
    }
    menu.appendChild(item);
    return item;
  });

  menu.addEventListener("keydown", (event) => _onContextMenuKeydown(event, items));
  document.body.appendChild(menu);
  _positionContextMenu(menu, anchor);
  _contextMenuEl = menu;

  const firstEnabled = items.find((item) => !item.disabled) || items[0];
  firstEnabled.tabIndex = 0;
  firstEnabled.focus();

  // Deferred so the same click/contextmenu event that opened the menu is
  // not also seen by this listener as an "outside" click.
  _contextMenuOutsideHandler = (event) => {
    if (!menu.contains(event.target)) _closeContextMenu();
  };
  window.setTimeout(() => {
    if (_contextMenuEl === menu) document.addEventListener("click", _contextMenuOutsideHandler);
  }, 0);
}

function _onContextMenuKeydown(event, items) {
  const enabled = items.filter((item) => !item.disabled);
  if (enabled.length === 0) return;
  const currentIndex = Math.max(0, enabled.indexOf(document.activeElement));
  const focusItem = (index) => {
    items.forEach((item) => { item.tabIndex = -1; });
    enabled[index].tabIndex = 0;
    enabled[index].focus();
  };
  switch (event.key) {
    case "ArrowDown":
      event.preventDefault();
      focusItem((currentIndex + 1) % enabled.length);
      return;
    case "ArrowUp":
      event.preventDefault();
      focusItem((currentIndex - 1 + enabled.length) % enabled.length);
      return;
    case "Home":
      event.preventDefault();
      focusItem(0);
      return;
    case "End":
      event.preventDefault();
      focusItem(enabled.length - 1);
      return;
    case "Tab":
      // A menu never traps Tab - it closes and lets Tab continue normally.
      _closeContextMenu();
      return;
    default:
      return;
  }
}

// Wires right-click and Shift+F10 (fired only when the item itself has
// focus, matching initRovingList()'s per-key guard) on every itemSelector
// row inside container to open a menu built by buildEntries(item). The
// visible per-item menu button is not created here - each row shape
// differs too much - callers wire its click to openItemContextMenu()
// directly instead, right where they build that button.
function initContextMenuTrigger(container, itemSelector, buildEntries) {
  if (!container || container.dataset.ctxMenuBound === "true") return;
  container.dataset.ctxMenuBound = "true";
  container.addEventListener("contextmenu", (event) => {
    const item = event.target.closest(itemSelector);
    if (!item) return;
    event.preventDefault();
    openContextMenu(buildEntries(item), { x: event.clientX, y: event.clientY }, item);
  });
  container.addEventListener("keydown", (event) => {
    if (event.key !== "F10" || !event.shiftKey) return;
    const item = event.target.closest(itemSelector);
    if (!item || event.target !== item) return;
    event.preventDefault();
    openContextMenu(buildEntries(item), item, item);
  });
}

function openItemContextMenu(item, anchorElement, buildEntries) {
  // Return focus to the button that opened the menu, not to `item` - the
  // two differ for every real caller (a per-row menu button is not the row
  // itself), and closing must land focus back where the user's Tab stop
  // already was, exactly like the shortcuts overlay's own return-focus
  // contract.
  openContextMenu(buildEntries(item), anchorElement, anchorElement);
}

// ---------------------------------------------------------------------
// Escape stack
// ---------------------------------------------------------------------
//
// Anything that can be "the topmost open thing" registers itself once;
// Escape closes the highest-priority entry that reports itself open.
// Iterated last-registered-first (LIFO), so something that registers later
// - such as task-ui-ux-2's context menu, drawn visually on top of
// everything registered here - naturally outranks the panels/dialogs this
// task registers, without either task needing to know about the other's
// registrations.
const _escapables = [];

function registerEscapable(entry) {
  _escapables.push(entry);
}

function handleGlobalEscape() {
  for (let i = _escapables.length - 1; i >= 0; i--) {
    if (_escapables[i].isOpen()) {
      _escapables[i].close();
      return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------
// Global keymap
// ---------------------------------------------------------------------

function _isTextEditableElement(element) {
  if (!element) return false;
  if (element.isContentEditable) return true;
  const tag = element.tagName;
  if (tag === "TEXTAREA") return true;
  if (tag !== "INPUT") return false;
  const type = (element.getAttribute("type") || "text").toLowerCase();
  return !["checkbox", "radio", "button", "submit", "range"].includes(type);
}

// True while a real modal (an `aria-modal="true"` dialog - deliberately
// looked up by the ARIA contract rather than a hardcoded id, so any future
// one gets the same treatment for free) or the context menu is open.
// `inert` already stops Tab/click/focus from reaching the background, but
// it does nothing about a document-level keydown listener like this one -
// marking the background inert while still letting a global shortcut act
// on it would make the dialog "modal" in name only. The context menu is
// not `aria-modal` (it does not trap Tab - see _onContextMenuKeydown's
// Tab case), but the same reasoning applies to it: Alt+N switching views
// out from under an open menu would be surprising, not useful.
function _hasOpenModal() {
  if (document.querySelector('[aria-modal="true"]:not([hidden])') !== null) return true;
  return _contextMenuOpen();
}

// view switching, "/" to the Journal search box, "?" for the shortcuts
// overlay, Escape via the stack above. Ctrl+Q is deliberately left unbound
// here - reserved for the future command palette (tasks/story-ui-ux-
// maturity.md) so nothing else claims it first. Everything except Escape
// is suppressed while a modal is open - Escape is how you leave it, not a
// reason to also let other global shortcuts reach past it.
function initGlobalKeymap() {
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      handleGlobalEscape();
      return;
    }
    if (_hasOpenModal()) return;
    if (_isTextEditableElement(event.target)) return; // never hijack real typing
    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const searchInput = document.getElementById("journalSearchQuery");
      const journalActive = document.documentElement.getAttribute("data-view") === "journal";
      if (searchInput && journalActive) {
        event.preventDefault();
        searchInput.focus();
      }
      return;
    }
    if (event.key === "?" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      if (typeof openShortcutsOverlay === "function") {
        event.preventDefault();
        openShortcutsOverlay();
      }
      return;
    }
    if (event.altKey && !event.ctrlKey && !event.metaKey) {
      const view = { 1: "status", 2: "journal", 3: "settings" }[event.key];
      // Only switches to a view #viewToggle actually offers a button for -
      // an accelerator must never reach further than the control it
      // accelerates (demo.html's harness carries no Journal button or
      // markup on purpose; Alt+2 there must stay as inert as the missing
      // button, not open a view with nothing to render into).
      const hasButton = view && document.querySelector(`#viewToggle button[data-view="${view}"]`);
      if (hasButton && typeof setActiveView === "function") {
        event.preventDefault();
        setActiveView(view);
      }
    }
  });
}
