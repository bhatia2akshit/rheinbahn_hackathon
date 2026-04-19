let socket = null;
let inputContext = null;
let outputContext = null;
let mediaStream = null;
let scriptNode = null;
let sourceNode = null;
let mutedGain = null;
let nextPlaybackTime = 0;
let pollHandle = null;
const autoOpenedEvents = new Set();
const reservedCallWindows = {
  police: null,
  rettungs: null,
};

const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const statusText = document.getElementById("statusText");
const conversationBox = document.getElementById("conversationBox");
const eventBox = document.getElementById("eventBox");
const driverNameInput = document.getElementById("driverNameInput");
const trainNumberInput = document.getElementById("trainNumberInput");

const DRIVER_NAME_STORAGE_KEY = "voice-driver-name";
const TRAIN_NUMBER_STORAGE_KEY = "voice-train-number";

function renderDispatchCalls(calls) {
  if (!calls || calls.length === 0) {
    return "";
  }

  const items = calls
    .map(
      (call) => `
        <div class="border rounded p-2 mt-2">
          <div><strong>${call.service_label}:</strong> ${call.route_label}</div>
          <div><strong>Number:</strong> ${call.display_phone_number}</div>
          <div><a href="${call.call_page_path}" target="_blank" rel="noopener noreferrer">Open ${call.service_label} Call</a></div>
        </div>
      `
    )
    .join("");

  return `<div class="mt-3"><strong>Dispatch Calls:</strong>${items}</div>`;
}

async function tryAutoOpenDispatchPage(eventId, calls) {
  if (!eventId || !calls || calls.length === 0 || autoOpenedEvents.has(eventId)) {
    return;
  }

  autoOpenedEvents.add(eventId);
  stopPolling();
  await disconnectVoice();
  openDispatchPages(calls);
}

function reserveDispatchWindows() {
  reserveDispatchWindow("police", "Opening police call...");
  reserveDispatchWindow("rettungs", "Opening rettung call...");
}

function reserveDispatchWindow(service, title) {
  const existing = reservedCallWindows[service];
  if (existing && !existing.closed) {
    return;
  }

  const handle = window.open("", `dispatch-${service}`);
  if (!handle) {
    reservedCallWindows[service] = null;
    return;
  }

  reservedCallWindows[service] = handle;
  handle.document.write(`
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="UTF-8">
        <title>${title}</title>
      </head>
      <body style="font-family: Arial, sans-serif; padding: 24px;">
        <p>${title}</p>
      </body>
    </html>
  `);
  handle.document.close();
}

function openDispatchPages(calls) {
  const requiredServices = new Set(calls.map((call) => call.service));

  calls.forEach((call) => {
    if (!call.call_page_path) {
      return;
    }

    const reservedWindow = reservedCallWindows[call.service];
    if (reservedWindow && !reservedWindow.closed) {
      reservedWindow.location.href = call.call_page_path;
      return;
    }

    window.open(call.call_page_path, "_blank", "noopener,noreferrer");
  });

  Object.keys(reservedCallWindows).forEach((service) => {
    if (requiredServices.has(service)) {
      return;
    }
    const reservedWindow = reservedCallWindows[service];
    if (reservedWindow && !reservedWindow.closed) {
      reservedWindow.close();
    }
    reservedCallWindows[service] = null;
  });
}

function setStatus(text) {
  statusText.textContent = text;
}

function loadSessionDefaults() {
  const storedDriverName = window.localStorage.getItem(DRIVER_NAME_STORAGE_KEY);
  const storedTrainNumber = window.localStorage.getItem(TRAIN_NUMBER_STORAGE_KEY);

  if (storedDriverName) {
    driverNameInput.value = storedDriverName;
  }
  if (storedTrainNumber) {
    trainNumberInput.value = storedTrainNumber;
  }
}

function persistSessionDefaults() {
  window.localStorage.setItem(DRIVER_NAME_STORAGE_KEY, driverNameInput.value.trim());
  window.localStorage.setItem(TRAIN_NUMBER_STORAGE_KEY, trainNumberInput.value.trim());
}

function buildVoiceSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const url = new URL(`${protocol}://${window.location.host}/ws/voice-agent`);

  const driverName = driverNameInput.value.trim();
  const trainNumber = trainNumberInput.value.trim();

  if (driverName) {
    url.searchParams.set("driver_name", driverName);
  }
  if (trainNumber) {
    url.searchParams.set("train_number", trainNumber);
  }

  return url.toString();
}

function toInt16Pcm(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i += 1) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function downsampleBuffer(buffer, sourceRate, targetRate) {
  if (targetRate >= sourceRate) {
    return buffer;
  }
  const ratio = sourceRate / targetRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i += 1) {
      accum += buffer[i];
      count += 1;
    }
    result[offsetResult] = count > 0 ? accum / count : 0;
    offsetResult += 1;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function playPcm16Chunk(arrayBuffer, sampleRate = 24000) {
  if (!outputContext) {
    outputContext = new AudioContext({ sampleRate });
  }
  const int16 = new Int16Array(arrayBuffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i += 1) {
    float32[i] = int16[i] / 0x8000;
  }

  const audioBuffer = outputContext.createBuffer(1, float32.length, sampleRate);
  audioBuffer.copyToChannel(float32, 0);

  const source = outputContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(outputContext.destination);
  const now = outputContext.currentTime;
  if (nextPlaybackTime < now) {
    nextPlaybackTime = now;
  }
  source.start(nextPlaybackTime);
  nextPlaybackTime += audioBuffer.duration;
}

async function refreshConversation() {
  try {
    const response = await fetch("/api/voice/conversation");
    if (!response.ok) return;
    const data = await response.json();

    const messages = (data.messages || []).map((msg) => `${msg.role}: ${msg.text}`);
    conversationBox.textContent = messages.join("\n");

    if (data.event && data.event.event_id) {
      const dispatchCalls = data.event.dispatch_calls || [];
      eventBox.innerHTML = `
        <div><strong>Event ID:</strong> ${data.event.event_id}</div>
        <div><strong>Driver Name:</strong> ${data.event.driver_name}</div>
        <div><strong>Train Number:</strong> ${data.event.train_number}</div>
        <div><strong>Timestamp:</strong> ${data.event.timestamp}</div>
        <div><strong>Location:</strong> ${data.event.location}</div>
        <div><strong>Description:</strong> ${data.event.description}</div>
        <div><strong>Status:</strong> ${data.event.status}</div>
        <div class="mt-2"><a href="/event/${data.event.event_id}" target="_blank" rel="noopener noreferrer">Open Event</a></div>
        ${renderDispatchCalls(dispatchCalls)}
      `;
      await tryAutoOpenDispatchPage(data.event.event_id, dispatchCalls);
    }
  } catch (_) {
    // ignore polling errors
  }
}

function startPolling() {
  refreshConversation();
  pollHandle = setInterval(refreshConversation, 1200);
}

function stopPolling() {
  if (pollHandle) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
}

async function startMicrophoneStreaming() {
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    },
  });

  inputContext = new AudioContext();
  sourceNode = inputContext.createMediaStreamSource(mediaStream);
  scriptNode = inputContext.createScriptProcessor(4096, 1, 1);
  mutedGain = inputContext.createGain();
  mutedGain.gain.value = 0;

  scriptNode.onaudioprocess = (event) => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const input = event.inputBuffer.getChannelData(0);
    const downsampled = downsampleBuffer(input, inputContext.sampleRate, 16000);
    const pcm16 = toInt16Pcm(downsampled);
    socket.send(pcm16.buffer);
  };

  sourceNode.connect(scriptNode);
  scriptNode.connect(mutedGain);
  mutedGain.connect(inputContext.destination);
}

async function connectVoice() {
  connectBtn.disabled = true;
  setStatus("Connecting to voice agent...");

  try {
    persistSessionDefaults();
    reserveDispatchWindows();

    const statusRes = await fetch("/api/voice/status");
    const statusData = await statusRes.json();
    if (!statusData.configured) {
      throw new Error(`Missing config: ${(statusData.missing_env_vars || []).join(", ")}`);
    }

    // Prepare audio capture first so backend doesn't start a session that receives no media.
    await startMicrophoneStreaming();

    socket = new WebSocket(buildVoiceSocketUrl());
    socket.binaryType = "arraybuffer";

    socket.onopen = () => {
      setStatus("Connected. Speak now.");
      disconnectBtn.disabled = false;
      startPolling();
    };

    socket.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        playPcm16Chunk(event.data, 24000);
        return;
      }
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "Error") {
          setStatus(`Agent error: ${payload.description || "unknown error"}`);
        }
      } catch (_) {
        // ignore non-json messages
      }
    };

    socket.onerror = () => {
      setStatus("Socket error");
    };

    socket.onclose = (event) => {
      const closeCode = event?.code ? ` (${event.code})` : "";
      const closeReason = event?.reason ? `: ${event.reason}` : "";
      setStatus(`Disconnected${closeCode}${closeReason}`);
      disconnectVoice();
    };
  } catch (error) {
    setStatus(`Connection failed: ${error.message}`);
    await disconnectVoice();
  } finally {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      connectBtn.disabled = false;
    }
  }
}

async function disconnectVoice() {
  stopPolling();

  if (scriptNode) {
    scriptNode.disconnect();
    scriptNode.onaudioprocess = null;
    scriptNode = null;
  }
  if (sourceNode) {
    sourceNode.disconnect();
    sourceNode = null;
  }
  if (mutedGain) {
    mutedGain.disconnect();
    mutedGain = null;
  }
  if (inputContext) {
    await inputContext.close();
    inputContext = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
  if (outputContext) {
    await outputContext.close();
    outputContext = null;
    nextPlaybackTime = 0;
  }
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close();
  }
  socket = null;
  disconnectBtn.disabled = true;
  connectBtn.disabled = false;
}

connectBtn.addEventListener("click", () => {
  connectVoice();
});

disconnectBtn.addEventListener("click", () => {
  disconnectVoice();
});

window.addEventListener("beforeunload", () => {
  disconnectVoice();
});

driverNameInput.addEventListener("change", persistSessionDefaults);
trainNumberInput.addEventListener("change", persistSessionDefaults);

loadSessionDefaults();
