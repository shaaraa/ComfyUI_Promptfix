import { app } from "../../scripts/app.js";

// Helper function to connect to our python extension backend WebSocket
function connectToPromptFixWebSocket() {
    let wsUrl = new URL(`/promptfix/ws?platform=cm`, window.location.href);
    wsUrl.protocol = wsUrl.protocol.replace('http', 'ws');
    
    let ws = new WebSocket(wsUrl.href);

    ws.onopen = () => {
        console.log("[PromptFix UI] Connected to plugin WebSocket");
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            console.log("[PromptFix UI] Received WS message: ", msg);
            
            // Trigger Queue Prompt
            if (msg.queue) {
                console.log("[PromptFix UI] Queue triggered from Photoshop!");
                // Click the queue button in ComfyUI
                app.queuePrompt(0, 1);
            }
        } catch (e) {
            console.error("[PromptFix UI] Error parsing WS message", e);
        }
    };

    ws.onclose = () => {
        console.log("[PromptFix UI] Disconnected. Reconnecting in 2s...");
        setTimeout(connectToPromptFixWebSocket, 2000);
    };

    ws.onerror = (e) => {
        console.error("[PromptFix UI] WebSocket error", e);
    };
}

// Hook into app loads
app.registerExtension({
    name: "PromptFix.Integration",
    async setup() {
        console.log("[PromptFix UI] Extension loaded. Initializing WebSocket connection.");
        connectToPromptFixWebSocket();
    }
});
