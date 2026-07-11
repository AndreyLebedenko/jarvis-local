// Shared protocol-v1 WebSocket client for the Status Console surfaces.

const UI_PROTOCOL_VERSION = 1;
let _uiTransportSocket = null;
let _uiTransportReconnectTimer = null;

function createTransportStatusHandler() {
  return (online, message) => {
    let indicator = document.getElementById("transportStatus");
    if (!indicator) {
      indicator = document.createElement("div");
      indicator.id = "transportStatus";
      indicator.className = "transport-status";
      document.body.prepend(indicator);
    }
    indicator.textContent = message || "";
    document.documentElement.setAttribute("data-transport", online ? "online" : "offline");
  };
}

function dispatchStateDelta(payload, handlers) {
  const handler = handlers[payload.key];
  if (!handler) {
    console.warn("Ignoring unknown UI state delta:", payload.key);
    return;
  }
  handler(payload.value);
}

function startUiTransport(clientId, capabilities, handlers) {
  const connect = () => connectUiTransport(clientId, capabilities, handlers);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", connect);
  } else {
    connect();
  }
}

function connectUiTransport(clientId, capabilities, handlers) {
  const token = new URLSearchParams(window.location.search).get("token");
  if (!token) {
    handlers.onStatus(false, "Нет токена UI transport в URL");
    return;
  }
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${scheme}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
  _uiTransportSocket = new WebSocket(url);
  _uiTransportSocket.onopen = () => {
    _uiTransportSocket.send(JSON.stringify({
      protocol: UI_PROTOCOL_VERSION,
      channel: "control",
      type: "hello",
      payload: { client_id: clientId, capabilities },
    }));
  };
  _uiTransportSocket.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.protocol !== UI_PROTOCOL_VERSION) {
        throw new Error("Unsupported UI transport protocol");
      }
      if (message.channel === "state" && message.type === "snapshot") {
        handlers.onSnapshot(message.payload);
        handlers.onStatus(true, "");
      } else if (message.channel === "state" && message.type === "delta") {
        handlers.onDelta(message.payload);
      } else if (message.channel === "control" && message.type === "error") {
        handlers.onError(message.payload.message);
      }
    } catch (error) {
      console.error("UI transport message failed:", error);
      handlers.onStatus(false, "Ошибка данных UI transport");
    }
  };
  _uiTransportSocket.onerror = () => handlers.onStatus(false, "Нет связи с engine");
  _uiTransportSocket.onclose = () => {
    handlers.onStatus(false, "Нет связи с engine");
    if (_uiTransportReconnectTimer === null) {
      _uiTransportReconnectTimer = window.setTimeout(() => {
        _uiTransportReconnectTimer = null;
        connectUiTransport(clientId, capabilities, handlers);
      }, 1000);
    }
  };
}

function sendUiControl(command, argumentsObject = {}) {
  if (!_uiTransportSocket || _uiTransportSocket.readyState !== WebSocket.OPEN) {
    return false;
  }
  _uiTransportSocket.send(JSON.stringify({
    protocol: UI_PROTOCOL_VERSION,
    channel: "control",
    type: "command",
    payload: { command, arguments: argumentsObject },
  }));
  return true;
}
