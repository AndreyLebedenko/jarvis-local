// Words for the content-free record of a personal-proxy notice: its kind, and
// the enum, number or finding positions that go with it. The Journal view and
// the "last block reason" of the Status view both draw it from here, so the two
// can never word the same notice differently. Nothing here ever holds a value
// taken from a request: only categories and character positions.

// A stored record can outlive the catalog that wrote it: an unknown kind or
// category reads as neutral text, never as an error or a raw identifier.
function _proxyWording(key, unknownKey) {
  const text = optionalUiString(key);
  return text === null ? uiString(unknownKey) : text;
}

function _proxyFindingText(finding) {
  const category = _proxyWording(
    "proxy_gate_category_" + finding.category, "proxy_gate_category_unknown");
  const position = uiString("proxy_gate_position")
    .replace("{message}", String(finding.message_index))
    .replace("{start}", String(finding.start))
    .replace("{end}", String(finding.end));
  return category + ", " + position;
}

function _proxyNoticeDetailText(detail) {
  if (detail === null || detail === undefined) return "";
  if (Array.isArray(detail)) return detail.map(_proxyFindingText).join("; ");
  if (typeof detail === "number") return String(detail);
  return optionalUiString("proxy_detail_" + detail) || "";
}

function proxyNoticeText(kind, detail) {
  const label = _proxyWording("proxy_notice_" + kind, "proxy_notice_unknown");
  const extra = _proxyNoticeDetailText(detail);
  return extra ? label + " (" + extra + ")" : label;
}
