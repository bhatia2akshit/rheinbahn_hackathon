let socket = null;
let inputContext = null;
let outputContext = null;
let mediaStream = null;
let scriptNode = null;
let sourceNode = null;
let mutedGain = null;
let nextPlaybackTime = 0;

const page = document.getElementById("callPage");
const acceptBtn = document.getElementById("acceptBtn");
const hangupBtn = document.getElementById("hangupBtn");
const statusText = document.getElementById("statusText");

function setStatus(text) {
  statusText.textContent = text;
}

function buildCallSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const url = new URL(`${protocol}://${window.location.host}/ws/call-agent`);
  url.searchParams.set("event_id", page.dataset.eventId);
  url.searchParams.set("service", page.dataset.service);
  return url.toString();
}

function toInt16Pcm(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, float32[i]));
    out[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
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
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    const input = event.inputBuffer.getChannelData(0);
    const downsampled = downsampleBuffer(input, inputContext.sampleRate, 16000);
    const pcm16 = toInt16Pcm(downsampled);
    socket.send(pcm16.buffer);
  };

  sourceNode.connect(scriptNode);
  scriptNode.connect(mutedGain);
  mutedGain.connect(inputContext.destination);
}

async function acceptCall() {
  acceptBtn.disabled = true;
  setStatus("Connecting accepted call...");

  try {
    await startMicrophoneStreaming();

    socket = new WebSocket(buildCallSocketUrl());
    socket.binaryType = "arraybuffer";

    socket.onopen = () => {
      setStatus("Connected. Human should speak first.");
      hangupBtn.disabled = false;
    };

    socket.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        playPcm16Chunk(event.data, 24000);
        setStatus("AI is briefing the dispatcher.");
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
      setStatus("Call socket error");
    };

    socket.onclose = (event) => {
      const closeCode = event?.code ? ` (${event.code})` : "";
      const closeReason = event?.reason ? `: ${event.reason}` : "";
      setStatus(`Call ended${closeCode}${closeReason}`);
      disconnectCall();
    };
  } catch (error) {
    setStatus(`Call setup failed: ${error.message}`);
    await disconnectCall();
  }
}

async function disconnectCall() {
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
  hangupBtn.disabled = true;
  acceptBtn.disabled = false;
}

acceptBtn.addEventListener("click", () => {
  acceptCall();
});

hangupBtn.addEventListener("click", () => {
  disconnectCall();
});

window.addEventListener("beforeunload", () => {
  disconnectCall();
});
