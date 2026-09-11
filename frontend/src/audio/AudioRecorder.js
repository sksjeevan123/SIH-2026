```javascript
class AudioRecorder {
    constructor({
        wsUrl = "ws://localhost:8000/ws/audio",
        sampleRate = 16000,
        chunkDurationMs = 2000,
        onStatus = () => {},
        onChunk = () => {},
        onResult = () => {},
        onError = () => {}
    } = {}) {
        this.wsUrl = wsUrl;
        this.sampleRate = sampleRate;
        this.chunkDurationMs = chunkDurationMs;

        this.onStatus = onStatus;
        this.onChunk = onChunk;
        this.onResult = onResult;
        this.onError = onError;

        this.stream = null;
        this.audioContext = null;
        this.source = null;
        this.worklet = null;
        this.socket = null;

        this.buffer = [];
        this.bufferSamples = 0;

        this.chunkId = 0;
        this.callStartTime = 0;
        this.running = false;
        this.stopping = false;
    }

    async start() {
        if (this.running) return;

        try {
            this.onStatus("Requesting microphone...");

            // Get microphone
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: false
                }
            });

            // Create audio context
            this.audioContext = new AudioContext({
                sampleRate: this.sampleRate,
                latencyHint: "interactive"
            });

            // Load AudioWorklet
            await this.audioContext.audioWorklet.addModule(
                "./audioProcessor.js"
            );

            // Create microphone source
            this.source =
                this.audioContext.createMediaStreamSource(
                    this.stream
                );

            // Create processor
            this.worklet = new AudioWorkletNode(
                this.audioContext,
                "audio-processor",
                {
                    numberOfInputs: 1,
                    numberOfOutputs: 1,
                    channelCount: 1
                }
            );

            // Receive PCM from AudioWorklet
            this.worklet.port.onmessage = event => {
                this.handleAudio(event.data);
            };

            this.worklet.onprocessorerror = () => {
                this.handleError(
                    "Audio processor error"
                );
            };

            /*
             * Keep AudioWorklet alive without
             * playing microphone audio to speakers.
             */
            const silentGain =
                this.audioContext.createGain();

            silentGain.gain.value = 0;

            this.source.connect(this.worklet);
            this.worklet.connect(silentGain);
            silentGain.connect(
                this.audioContext.destination
            );

            // Connect WebSocket
            this.socket = new WebSocket(this.wsUrl);
            this.socket.binaryType = "arraybuffer";

            this.socket.onopen = () => {
                this.sendSessionInfo();
                this.onStatus("Connected");
            };

            this.socket.onmessage = event => {
                this.handleServerMessage(event.data);
            };

            this.socket.onerror = () => {
                this.handleError(
                    "WebSocket connection error"
                );
            };

            this.socket.onclose = () => {
                if (
                    this.running &&
                    !this.stopping
                ) {
                    this.onStatus(
                        "WebSocket disconnected"
                    );
                }
            };

            await this.waitForSocket();

            // Resume audio context if suspended
            if (
                this.audioContext.state ===
                "suspended"
            ) {
                await this.audioContext.resume();
            }

            this.buffer = [];
            this.bufferSamples = 0;
            this.chunkId = 0;
            this.callStartTime =
                performance.now();

            this.running = true;
            this.stopping = false;

            this.onStatus("Recording");
        } catch (error) {
            this.handleError(error);
        }
    }

    handleAudio(samples) {
        if (!this.running) return;

        if (!(samples instanceof Float32Array)) {
            samples = new Float32Array(samples);
        }

        this.buffer.push(samples);
        this.bufferSamples += samples.length;

        const requiredSamples =
            Math.floor(
                this.sampleRate *
                this.chunkDurationMs /
                1000
            );

        while (
            this.bufferSamples >=
            requiredSamples
        ) {
            const chunk =
                this.extractSamples(
                    requiredSamples
                );

            this.sendChunk(chunk);
        }
    }

    extractSamples(requiredSamples) {
        const output =
            new Float32Array(
                requiredSamples
            );

        let offset = 0;

        while (
            offset < requiredSamples &&
            this.buffer.length > 0
        ) {
            const current =
                this.buffer[0];

            const copyLength =
                Math.min(
                    current.length,
                    requiredSamples - offset
                );

            output.set(
                current.subarray(
                    0,
                    copyLength
                ),
                offset
            );

            offset += copyLength;
            this.bufferSamples -= copyLength;

            if (
                copyLength ===
                current.length
            ) {
                this.buffer.shift();
            } else {
                this.buffer[0] =
                    current.subarray(
                        copyLength
                    );
            }
        }

        return output;
    }

    sendSessionInfo() {
        if (
            !this.socket ||
            this.socket.readyState !==
            WebSocket.OPEN
        ) {
            return;
        }

        this.socket.send(
            JSON.stringify({
                type: "start",
                sample_rate: this.sampleRate,
                channels: 1,
                format: "pcm_f32le",
                chunk_duration_ms:
                    this.chunkDurationMs
            })
        );
    }

    sendChunk(samples) {
        if (
            !this.socket ||
            this.socket.readyState !==
            WebSocket.OPEN
        ) {
            return;
        }

        const timestamp =
            Math.round(
                performance.now() -
                this.callStartTime
            );

        const metadata = {
            type: "audio",
            chunk_id: this.chunkId,
            timestamp_ms: timestamp,
            duration_ms:
                this.chunkDurationMs,
            sample_rate:
                this.sampleRate,
            channels: 1,
            format: "pcm_f32le",
            samples: samples.length
        };

        // Send metadata
        this.socket.send(
            JSON.stringify(metadata)
        );

        // Send raw PCM
        const audioBuffer =
            samples.buffer.slice(
                samples.byteOffset,
                samples.byteOffset +
                samples.byteLength
            );

        this.socket.send(audioBuffer);

        this.onChunk({
            id: this.chunkId,
            timestamp: timestamp,
            duration:
                this.chunkDurationMs,
            samples: samples.length
        });

        this.chunkId++;
    }

    handleServerMessage(data) {
        try {
            const result =
                typeof data === "string"
                    ? JSON.parse(data)
                    : data;

            if (
                result.type === "result"
            ) {
                this.onResult(result);
            }
        } catch (error) {
            console.warn(
                "Invalid server response:",
                error
            );
        }
    }

    waitForSocket(timeout = 10000) {
        return new Promise(
            (resolve, reject) => {
                if (
                    this.socket &&
                    this.socket.readyState ===
                    WebSocket.OPEN
                ) {
                    resolve();
                    return;
                }

                const start =
                    Date.now();

                const check = () => {
                    if (
                        this.socket &&
                        this.socket.readyState ===
                        WebSocket.OPEN
                    ) {
                        resolve();
                        return;
                    }

                    if (
                        Date.now() - start >
                        timeout
                    ) {
                        reject(
                            new Error(
                                "WebSocket connection timeout"
                            )
                        );
                        return;
                    }

                    setTimeout(
                        check,
                        50
                    );
                };

                check();
            }
        );
    }

    stop() {
        if (
            !this.running &&
            !this.stream
        ) {
            return;
        }

        this.stopping = true;
        this.running = false;

        if (this.worklet) {
            this.worklet.port.postMessage({
                type: "stop"
            });
        }

        if (this.source) {
            this.source.disconnect();
            this.source = null;
        }

        if (this.worklet) {
            this.worklet.disconnect();
            this.worklet = null;
        }

        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }

        if (this.stream) {
            this.stream
                .getTracks()
                .forEach(track => {
                    track.stop();
                });

            this.stream = null;
        }

        if (this.socket) {
            if (
                this.socket.readyState ===
                WebSocket.OPEN ||
                this.socket.readyState ===
                WebSocket.CONNECTING
            ) {
                this.socket.close(
                    1000,
                    "Recording stopped"
                );
            }

            this.socket = null;
        }

        this.buffer = [];
        this.bufferSamples = 0;

        this.onStatus("Stopped");
    }

    handleError(error) {
        console.error(
            "AudioRecorder:",
            error
        );

        this.onError(
            error instanceof Error
                ? error.message
                : String(error)
        );

        this.stop();
    }

    isRecording() {
        return this.running;
    }
}

export default AudioRecorder;
```