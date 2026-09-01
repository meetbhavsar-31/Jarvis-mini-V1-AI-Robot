/* =========================================================================
   JARVIS DASHBOARD — SCRIPT.JS
   ========================================================================= */

// Bulletproof Loader Hider
const forceHideLoader = () => {
  try {
    // 1. Target by common IDs
    const loaderIds = ['loading-screen', 'loader', 'preloader', 'splash-screen'];
    loaderIds.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });

    // 2. Target by common classes
    const loaderClasses = ['.loading-screen', '.preloader', '.splash-screen'];
    loaderClasses.forEach(cls => {
      document.querySelectorAll(cls).forEach(el => el.style.display = 'none');
    });

    // 3. Fallback: Target the specific text overlay if the ID is missing
    document.querySelectorAll('div').forEach(div => {
      if (div.style.display !== 'none' && div.innerHTML.includes('INITIALIZING NEURAL')) {
        // Confirm it's an overlay layer by checking position or just hide it
        if (getComputedStyle(div).position === 'fixed' || getComputedStyle(div).position === 'absolute') {
          div.style.display = 'none';
        }
      }
    });
  } catch (e) {
    console.error("Loader hiding error:", e);
  }
};

document.addEventListener("DOMContentLoaded", () => {
  initBurgerMenu();
  initLiveClock();
  initQuickActionButtons();   
  initDpadControls();         
  initCameraPage();           
  initVoiceAssistantPage();   
  initSettingsForm();         
  initSystemPage();           
  initLogsPage();             
  initDashboardPage();        
  initDashboardChat();
  initHandsFreeMode(); 
  initEyeColorPicker();
  initLanguageToggle();
  initAutonomyToggle(); // <-- ADD THIS NEW LINE

  // Force hide the loader instantly as a fail-safe
  setTimeout(forceHideLoader, 1500); 
});

window.addEventListener("load", () => {
  setTopbarHeightVar();
  forceHideLoader(); // Ensure it vanishes as soon as the DOM fully loads

  // LAZY LOAD VIDEO FEED
  // This prevents the browser from hanging on the video stream if the robot is offline.
  setTimeout(() => {
    const camImg = document.getElementById("liveCameraFeed");
    if (camImg && camImg.getAttribute("data-src")) {
      camImg.src = camImg.getAttribute("data-src");
    }
  }, 1000); 
});
window.addEventListener("resize", setTopbarHeightVar);

function setTopbarHeightVar() {
  const topbar = document.querySelector(".topbar");
  if (!topbar) return;
  document.documentElement.style.setProperty("--topbar-h", `${topbar.offsetHeight}px`);
}

/* ------------------------------------------------------------------------
   TOP BAR — burger menu + live clock
   ------------------------------------------------------------------------ */

function initBurgerMenu() {
  const burgerBtn = document.getElementById("burgerBtn");
  const sideNav = document.getElementById("sideNav");
  const navOverlay = document.getElementById("navOverlay");
  if (!burgerBtn || !sideNav || !navOverlay) return;

  const closeNav = () => {
    sideNav.classList.remove("open");
    navOverlay.classList.remove("visible");
  };
  const toggleNav = () => {
    sideNav.classList.toggle("open");
    navOverlay.classList.toggle("visible");
  };

  burgerBtn.addEventListener("click", toggleNav);
  navOverlay.addEventListener("click", closeNav);
}

function initLiveClock() {
  const clockEl = document.getElementById("liveClock");
  if (!clockEl) return;
  const tick = () => {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString([], { hour12: false });
  };
  tick();
  setInterval(tick, 1000);
}

/* ------------------------------------------------------------------------
   UI & HARDWARE HELPERS 
   ------------------------------------------------------------------------ */

function initEyeColorPicker() {
  const swatches = document.querySelectorAll(".eye-color-swatch");
  const miniFace = document.getElementById("miniFaceCard");

  if (!swatches.length) return;

  swatches.forEach((swatch) => {
    swatch.addEventListener("click", () => {
      swatches.forEach((s) => s.classList.remove("active"));
      swatch.classList.add("active");
      
      const colorName = swatch.dataset.color || "teal";
      
      if (miniFace) {
        const hexColor = swatch.style.getPropertyValue("--swatch-color") || swatch.style.backgroundColor;
        miniFace.style.color = hexColor;
      }

      sendControlCommand(`eye_color_${colorName}`);
    });
  });
}

function initLanguageToggle() {
  const langButtons = document.querySelectorAll(".lang-btn");
  if (!langButtons.length) return;

  langButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      langButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      
      const selectedLang = btn.dataset.lang || 'en';

      if (typeof handsFreeRecognition !== 'undefined' && handsFreeRecognition) {
        handsFreeRecognition.lang = selectedLang === 'hi' ? 'hi-IN' : 'en-US';
      }

      fetch('/api/language', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({language: selectedLang})
      });
    });
  });
}

async function sendControlCommand(direction) {
  try {
    const res = await fetch("/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: direction }),
    });
    return await res.json();
  } catch (err) {
    console.error("sendControlCommand failed:", err);
  }
}

function initQuickActionButtons() {
  document.querySelectorAll("[data-command]").forEach((btn) => {
    btn.addEventListener("click", () => sendControlCommand(btn.dataset.command));
  });
}

function timeAgoLabel(isoTimestamp) {
  try {
    const d = new Date(isoTimestamp);
    return d.toLocaleTimeString([], { hour12: false });
  } catch {
    return "";
  }
}

/* ------------------------------------------------------------------------
   HANDS FREE MODE 
   ------------------------------------------------------------------------ */
let handsFreeMode = false;
let handsFreeRecognition = null;

function initHandsFreeMode() {
  const btn = document.getElementById('handsFreeBtn');
  if (!btn) return;

  btn.addEventListener("click", () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        alert("Hands-Free mode requires Google Chrome or Microsoft Edge.");
        return;
    }

    if (!handsFreeRecognition) {
        handsFreeRecognition = new SpeechRecognition();
        handsFreeRecognition.continuous = true;
        handsFreeRecognition.interimResults = false;

        handsFreeRecognition.onresult = function(event) {
            const transcript = event.results[event.results.length - 1][0].transcript.trim();
            const lower = transcript.toLowerCase();
            if (lower.includes("jarvis") || lower.includes("जारविस")) {
                const input = document.getElementById('dashboardChatInput');
                if(input) input.value = transcript;
                document.getElementById('dashboardChatForm').dispatchEvent(new Event('submit')); 
            }
        };

        handsFreeRecognition.onend = function() {
            if (handsFreeMode) {
                setTimeout(() => {
                    try { handsFreeRecognition.start(); } catch(e) {}
                }, 250);
            }
        };
    }

    handsFreeMode = !handsFreeMode;
    
    let currentLang = 'en';
    const activeLangBtn = document.querySelector('.lang-btn.active');
    if(activeLangBtn) currentLang = activeLangBtn.dataset.lang;

    if (handsFreeMode) {
        handsFreeRecognition.lang = currentLang === 'hi' ? 'hi-IN' : 'en-US';
        try { handsFreeRecognition.start(); } catch(e) {}
        btn.innerText = "HANDS-FREE WAKE WORD: ON";
        btn.style.background = "#da3633"; 
    } else {
        handsFreeRecognition.stop();
        btn.innerText = "HANDS-FREE WAKE WORD: OFF";
        btn.style.background = "#1f6feb"; 
    }
  });
}

/* ------------------------------------------------------------------------
   AUTONOMY TOGGLE BUTTON
   ------------------------------------------------------------------------ */
function initAutonomyToggle() {
  const autoBtn = document.getElementById("autonomyToggleBtn");
  if (!autoBtn) return;

  let isAutonomyActive = false;

  autoBtn.addEventListener("click", () => {
    isAutonomyActive = !isAutonomyActive;

    if (isAutonomyActive) {
      // Turn Button RED
      autoBtn.style.backgroundColor = "#da3633";
      autoBtn.style.borderColor = "#da3633";
      autoBtn.style.color = "white";
      autoBtn.textContent = "Stop Autonomy";
      sendControlCommand("autonomy_start");
    } else {
      // Revert Button to Default BLUE
      autoBtn.style.backgroundColor = "";
      autoBtn.style.borderColor = "";
      autoBtn.textContent = "Start Autonomy";
      sendControlCommand("autonomy_stop");
    }
  });
}

/* ------------------------------------------------------------------------
   DASHBOARD PAGES
   ------------------------------------------------------------------------ */

function initDashboardPage() {
  const batteryPercent = document.getElementById("batteryPercent");
  const batteryState = document.getElementById("batteryState");
  const batterySource = document.getElementById("batterySource");
  const activityLogCompact = document.getElementById("activityLogCompact");

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 4000);

  fetch("/api/robot-status", { signal: controller.signal })
    .then((r) => r.json())
    .then((data) => {
      clearTimeout(timeoutId);
      if (batteryPercent) batteryPercent.textContent = `${data.battery_percent}%`;
      if (batteryState) batteryState.textContent = data.charging ? "Charging" : "Discharging";
      if (batterySource) batterySource.textContent = data.power_source;
    })
    .catch((err) => console.warn("Robot status fallback UI applied."))
    .finally(() => {
      forceHideLoader();
    });

  if (activityLogCompact) {
    fetch("/api/activity-log")
      .then((r) => r.json())
      .then((events) => {
        activityLogCompact.innerHTML = "";
        events.slice(0, 6).forEach((item) => {
          const li = document.createElement("li");
          li.innerHTML = `<span>${item.event}</span><span class="log-time" style="font-size:10px; color:#56698a;">${timeAgoLabel(item.timestamp)}</span>`;
          activityLogCompact.appendChild(li);
        });
      })
      .catch((err) => console.warn("Activity log fetch fallback UI applied."));
  }
}

function initDashboardChat() {
  const chatForm = document.getElementById("dashboardChatForm");
  const chatInput = document.getElementById("dashboardChatInput");
  const chatMessages = document.getElementById("dashboardChatMessages");
  const micBtn = document.getElementById("dashboardMicButton");
  const chips = document.querySelectorAll(".card-chat .chip");

  if (!chatForm) return;

  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;
    sendChatMessage(text);
    chatInput.value = "";
  });

  chips.forEach((chip) => {
    chip.addEventListener("click", () => sendChatMessage(chip.dataset.commandText));
  });

  let isListening = false;
  let mediaRecorder;
  let audioChunks = [];

  if (micBtn) {
    micBtn.addEventListener("click", async () => {
      if (isListening) {
          mediaRecorder.stop();
          micBtn.classList.remove("listening");
          micBtn.innerHTML = "&#127908;";
          isListening = false;
          return;
      }
      
      if (handsFreeMode) {
          document.getElementById('handsFreeBtn').click(); 
      }

      try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          mediaRecorder = new MediaRecorder(stream);
          audioChunks = [];
          mediaRecorder.ondataavailable = event => { audioChunks.push(event.data); };
          
          mediaRecorder.onstop = async () => {
              const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
              const formData = new FormData();
              formData.append("audio", audioBlob, "speech.webm");
              chatInput.value = "Transcribing...";
              try {
                  const response = await fetch('/api/stt', { method: 'POST', body: formData });
                  const data = await response.json();
                  if (data.text) {
                      chatInput.value = data.text;
                      chatForm.dispatchEvent(new Event('submit')); 
                  } else {
                      chatInput.value = "";
                  }
              } catch (e) {
                  chatInput.value = "STT Error.";
              }
              stream.getTracks().forEach(track => track.stop());
          };
          
          mediaRecorder.start();
          isListening = true;
          micBtn.classList.add("listening");
          micBtn.innerHTML = "&#9209;"; 
      } catch (err) {
          alert("Microphone permission required.");
      }
    });
  }

  function sendChatMessage(text) {
    const emptyMsg = chatMessages.querySelector(".response-empty");
    if (emptyMsg) emptyMsg.remove();
    
    const liUser = document.createElement("li");
    liUser.innerHTML = `<div style="color: #8fa7c4; font-size: 11px; margin-bottom: 2px;">You: ${text}</div>`;
    chatMessages.appendChild(liUser);
    
    const liAi = document.createElement("li");
    liAi.innerHTML = `<div style="color: #00bfff; font-size: 12.5px;">...</div>`;
    chatMessages.appendChild(liAi);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    let currentLang = 'en';
    const activeLangBtn = document.querySelector('.lang-btn.active');
    if(activeLangBtn) currentLang = activeLangBtn.dataset.lang;

    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, language: currentLang }),
    })
      .then((r) => r.json())
      .then((data) => {
         liAi.innerHTML = `<div style="color: #00bfff; font-size: 12.5px;">${data.response}</div>`;
         chatMessages.scrollTop = chatMessages.scrollHeight;
      })
      .catch((err) => {
         liAi.innerHTML = `<div style="color: #ff4d5e; font-size: 12.5px;">Error contacting AI backend.</div>`;
      });
  }
}

function initCameraPage() {
  const screenshotBtn = document.getElementById("takeScreenshotBtn");
  const recordBtn = document.getElementById("toggleRecordBtn");

  if (screenshotBtn) {
    screenshotBtn.addEventListener("click", () => sendControlCommand("screenshot"));
  }

  if (recordBtn) {
    let recording = false;
    recordBtn.addEventListener("click", () => {
      recording = !recording;
      recordBtn.textContent = recording ? "Stop Recording" : "Record Video";
      sendControlCommand(recording ? "record_start" : "record_stop");
    });
  }
}

function initDpadControls() {
  document.querySelectorAll(".dpad-btn[data-direction]").forEach((btn) => {
    btn.addEventListener("click", () => sendControlCommand(btn.dataset.direction));
  });
}

function initSystemPage() {
  const statCpu = document.getElementById("statCpu");
  if (!statCpu) return;

  const statCpuBar = document.getElementById("statCpuBar");
  const statMemory = document.getElementById("statMemory");
  const statMemoryBar = document.getElementById("statMemoryBar");
  const statNetwork = document.getElementById("statNetwork");
  const statNetworkLatency = document.getElementById("statNetworkLatency");
  const statStorage = document.getElementById("statStorage");
  const statStorageBar = document.getElementById("statStorageBar");

  function refreshStats() {
    fetch("/api/system-stats")
      .then((r) => r.json())
      .then((data) => {
        statCpu.textContent = `${data.cpu_percent}%`;
        statCpuBar.style.width = `${data.cpu_percent}%`;

        statMemory.textContent = `${data.memory_percent}%`;
        statMemoryBar.style.width = `${data.memory_percent}%`;

        statNetwork.textContent = data.network.status;
        statNetworkLatency.textContent = `Latency: ${data.network.latency_ms} ms`;

        statStorage.textContent = `${data.storage_percent}%`;
        statStorageBar.style.width = `${data.storage_percent}%`;
      })
      .catch((err) => {});
  }

  refreshStats();
  setInterval(refreshStats, 5000); 
}

function initLogsPage() {
  const activityLogFull = document.getElementById("activityLogFull");
  if (!activityLogFull) return;

  fetch("/api/activity-log")
    .then((r) => r.json())
    .then((events) => {
      activityLogFull.innerHTML = "";
      events.forEach((item) => {
        const li = document.createElement("li");
        li.innerHTML = `<span>${item.event}</span><span class="log-time" style="color: #56698a;">${timeAgoLabel(item.timestamp)}</span>`;
        activityLogFull.appendChild(li);
      });
    })
    .catch((err) => {});
}

function initSettingsForm() {}
function initVoiceAssistantPage() {}