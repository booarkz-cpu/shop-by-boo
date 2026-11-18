const {JSDOM} = require("jsdom");

const {window} = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://localhost/",
  pretendToBeVisual: true,
});

// Events, files and DOM elements must come from the same window as the document.
const useWindow = new Set([
  "window", "document", "navigator", "Event", "EventTarget", "Blob", "File",
  "FormData", "DOMException", "URL", "MouseEvent", "CustomEvent",
]);
for (const name of Object.getOwnPropertyNames(window)) {
  if (name in globalThis && !useWindow.has(name)) continue;
  Object.defineProperty(globalThis, name, {
    configurable: true,
    writable: true,
    value: window[name],
  });
}
