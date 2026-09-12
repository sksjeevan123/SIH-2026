import websocketService from "../services/websocket.js";

class AudioRecorder {
    constructor({
        sampleRate = 16000,
        chunkDurationMs = 4000,
        onStatus = () => {},
        onChunk = () => {},
        onResult = () => {},
        onError = () => {}
    } = {}) {
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
        this.silentGain = null;

        this.buffer = new Float32Array(0);
        this.bufferSamples = 0;

        this.requiredSamples =
            Math.round(
                this.sampleRate *
                this.chunkDurationMs /
                1000
            );

        this.chunkId = 0;
        this.callStartTime = 0;

        this.running = false;
        this.stopping = false;
        this.messageHandler = null;
    }

    async start() {
        if (this.running) {
            return;
        }

        try {
            this.stopping = false;

            this.onStatus("Requesting microphone...");

            this.stream =
                await navigator.mediaDevices.getUserMedia({
                    audio: {
                        channelCount: 1,
                        sampleRate: this.sampleRate,
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: false
                    }
                });

            this.audioContext =
                new AudioContext({
                    sampleRate: this.sampleRate,
                    latencyHint: "interactive"
                });

            if (
                this.audioContext.sampleRate !==
                this.sampleRate
            ) {
                throw new Error(
                    `Unsupported sample rate: ${this.audioContext.sampleRate} Hz`
                );
            }

            await this.audioContext.audioWorklet.addModule(
                new URL(
                    "./audioProcessor.js",
                    import.meta.url
                )
            );

            this.source =
                this.audioContext.createMediaStreamSource(
                    this.stream
                );

            this.worklet =
                new AudioWorkletNode(
                    this.audioContext,
                    "audio-processor",
                    {
                        numberOfInputs: 1,
                        numberOfOutputs: 1,
                        channelCount: 1,
                        channelCountMode: "explicit",
                        channelInterpretation: "speakers"
                    }
                );

            this.worklet.port.onmessage =
                (event) => {
                    this.handleAudio(event.data);
                };

            this.worklet.onprocessorerror =
                () => {
                    this.handleError(
                        "Audio processor error"
                    );
                };

            this.silentGain =
                this.audioContext.createGain();

            this.silentGain.gain.value = 0;

            this.source.connect(this.worklet);

            this.worklet.connect(
                this.silentGain
            );

            this.silentGain.connect(
                this.audioContext.destination
            );

            await websocketService.connect();

            this.messageHandler = (data) => {
                this.handleServerMessage(data);
            };

            websocketService.onMessage(
                this.messageHandler
            );

            if (
                this.audioContext.state ===
                "suspended"
            ) {
                await this.audioContext.resume();
            }

            this.buffer = new Float32Array(0);
            this.bufferSamples = 0;
            this.chunkId = 0;
            this.callStartTime = performance.now();

            this.running = true;

            websocketService.sendJson({
                type: "start",
                sample_rate: this.sampleRate,
                channels: 1,
                format: "pcm_f32le",
                chunk_duration_ms:
                    this.chunkDurationMs
            });

            this.onStatus("Recording");

        } catch (error) {
            this.handleError(error);
        }
    }

    handleAudio(samples) {
        if (!this.running) {
            return;
        }

        if (!(samples instanceof Float32Array)) {
            samples =
                new Float32Array(samples);
        }

        if (samples.length === 0) {
            return;
        }

        const combined =
            new Float32Array(
                this.bufferSamples +
                samples.length
            );

        combined.set(this.buffer);

        combined.set(
            samples,
            this.bufferSamples
        );

        this.buffer = combined;
        this.bufferSamples =
            combined.length;

        while (
            this.bufferSamples >=
            this.requiredSamples
        ) {
            const chunk =
                this.buffer.slice(
                    0,
                    this.requiredSamples
                );

            this.buffer =
                this.buffer.slice(
                    this.requiredSamples
                );

            this.bufferSamples =
                this.buffer.length;

            this.sendChunk(chunk);
        }
    }

    sendChunk(samples) {
        if (!this.running) {
            return;
        }

        if (!websocketService.isOpen()) {
            this.handleError(
                "WebSocket is not connected"
            );
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
            sample_rate: this.sampleRate,
            channels: 1,
            format: "pcm_f32le",
            samples: samples.length
        };

        websocketService.sendJson(metadata);

        const audioBuffer =
            samples.buffer.slice(
                samples.byteOffset,
                samples.byteOffset +
                samples.byteLength
            );

        websocketService.sendBinary(
            audioBuffer
        );

        this.onChunk({
            id: this.chunkId,
            timestamp,
            duration: this.chunkDurationMs,
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
                result?.type === "result" ||
                result?.type === "error"
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
            try {
                this.worklet.port.postMessage({
                    type: "stop"
                });
            } catch {}

            this.worklet.disconnect();
            this.worklet.port.onmessage = null;
            this.worklet.onprocessorerror = null;
            this.worklet = null;
        }

        if (this.source) {
            this.source.disconnect();
            this.source = null;
        }

        if (this.silentGain) {
            this.silentGain.disconnect();
            this.silentGain = null;
        }

        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }

        if (this.stream) {
            this.stream
                .getTracks()
                .forEach(
                    (track) => track.stop()
                );

            this.stream = null;
        }

        if (websocketService.isOpen()) {
            websocketService.sendJson({
                type: "stop"
            });

            websocketService.close();
        }

        this.buffer =
            new Float32Array(0);

        this.bufferSamples = 0;
        this.chunkId = 0;

        this.onStatus("Stopped");
    }

    handleError(error) {
        console.error(
            "AudioRecorder:",
            error
        );

        const message =
            error instanceof Error
                ? error.message
                : String(error);

        this.onError(message);

        this.stop();
    }

    isRecording() {
        return this.running;
    }
}

export default AudioRecorder;
