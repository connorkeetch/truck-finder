// Truck Finder Capture: runs only when the user clicks the toolbar button (activeTab).
// It reads the user's current text selection, page title and URL — nothing else — and delivers them to the
// local app at 127.0.0.1. No background scripts, no navigation, no network requests to the website.

const RECEIVER = "http://127.0.0.1:8765/capture";
const BLOCKED = ["facebook.com", "messenger.com", "fb.com"]; // Meta prohibits automated collection: manual entry only

const statusEl = document.getElementById("status");
const previewEl = document.getElementById("preview");
const sendBtn = document.getElementById("send");
const copyBtn = document.getElementById("copy");

function show(msg, cls = "") {
  statusEl.textContent = msg;
  statusEl.className = cls;
  statusEl.style.display = "block";
}

function isBlocked(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return BLOCKED.some((d) => host === d || host.endsWith("." + d));
  } catch (e) {
    return true;
  }
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function readSelection(tab) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => ({
      url: location.href,
      title: document.title,
      text: String(window.getSelection() || ""),
      // the page's own preview image (what link previews show), so you can recognise the truck later
      image: (document.querySelector('meta[property="og:image"]') || {}).content || "",
    }),
  });
  return result.result;
}

async function init() {
  const tab = await activeTab();
  if (!tab || !/^https?:/.test(tab.url || "")) {
    sendBtn.disabled = copyBtn.disabled = true;
    show("Open a listing page first.", "warn");
    return;
  }
  if (isBlocked(tab.url)) {
    sendBtn.disabled = copyBtn.disabled = true;
    show("Capture is turned off for Facebook. Please type the details into Truck Finder → Sources → Manual entry.", "warn");
    return;
  }
  try {
    const data = await readSelection(tab);
    if (data.text.trim()) {
      previewEl.textContent = data.text.slice(0, 600);
      previewEl.style.display = "block";
    } else {
      show("Nothing highlighted yet. Select the price, mileage, VIN and options on the page (or Ctrl+A), then reopen this popup.", "warn");
    }
  } catch (e) {
    show("This page can't be read (browser-protected page).", "warn");
    sendBtn.disabled = copyBtn.disabled = true;
  }
}

sendBtn.addEventListener("click", async () => {
  const tab = await activeTab();
  const data = await readSelection(tab);
  if (!data.text.trim()) {
    show("Highlight the listing details first.", "warn");
    return;
  }
  try {
    const resp = await fetch(RECEIVER, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const body = await resp.json();
    if (resp.ok) show(body.message || "Captured.", "ok");
    else show(body.error || `Truck Finder returned ${resp.status}`, "warn");
  } catch (e) {
    show("Truck Finder isn't running (or uses a different port). Use 'Copy for pasting' instead, then paste in Sources → Assisted capture.", "warn");
  }
});

copyBtn.addEventListener("click", async () => {
  const tab = await activeTab();
  const data = await readSelection(tab);
  await navigator.clipboard.writeText(`${data.url}\n${data.title}\n\n${data.text}`);
  show("Copied. In Truck Finder open Sources → Assisted capture → Paste, put the first line in 'Listing URL' and paste the rest.", "ok");
});

init();
