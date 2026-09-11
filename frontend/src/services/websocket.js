const SHARED_API_KEY = "voice_sih_2026_secure_key_99";

const DEFAULT_URL =
    (typeof import.meta !== "undefined" &&
        import.meta.env &&
        import.meta.env.VITE_WS_URL) ||
    `ws://127.0.0.1:8000/api/ws/audio?x_api_key=${SHARED_API_KEY}`;

class WebsocketService {
    constructor() {
        this.socket = null;
        this.messageHandler = null;
        this.url = DEFAULT_URL;
    }

    connect(url = this.url) {
        return new Promise((resolve, reject) => {
            if (this.isOpen()) {
                resolve();
                return;
            }

            this.url = url;
            this.socket = new WebSocket(url);
            this.socket.binaryType = "arraybuffer";

            this.socket.onopen = () => {
                resolve();
            };

            this.socket.onerror = () => {
                reject(new Error("WebSocket connection failed"));
            };

            this.socket.onmessage = (event) => {
                if (this.messageHandler) {
                    this.messageHandler(event.data);
                }
            };
        });
    }

    onMessage(handler) {
        this.messageHandler = handler;
    }

    isOpen() {
        return this.socket?.readyState === WebSocket.OPEN;
    }

    sendJson(payload) {
        if (!this.isOpen()) {
            return;
        }

        this.socket.send(JSON.stringify(payload));
    }

    sendBinary(buffer) {
        if (!this.isOpen()) {
            return;
        }

        this.socket.send(buffer);
    }

    close() {
        if (!this.socket) {
            return;
        }

        this.socket.close();
        this.socket = null;
    }
}

const websocketService = new WebsocketService();

export default websocketService;
