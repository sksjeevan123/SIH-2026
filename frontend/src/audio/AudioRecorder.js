import websocketService from "../services/websocket.js";

class AudioRecorder {
    constructor({
        sampleRate = 16000,
        chunkDurationMs = 2000,
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

        this.buffer = [];
        this.bufferSamples = 0;

        this.chunkId = 0;
        this.callStartTime = 0;

        this.running = false;
        this.stopping = false;
    }

    async start() {
        if (this.running) {
            return;
        }

        try {
            this.stopping = false;
            this.onStatus("Requesting microphone...");

            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: false
                }
            });

            this.audioContext = new AudioContext({
                sampleRate: this.sampleRate,
                latencyHint: "interactive"
            });

            await this.audioContext.audioWorklet.addModule(
                new URL("./audioProcessor.js", import.meta.url)
            );

            this.source =
                this.audioContext.createMediaStreamSource(
                    this.stream
                );

            this.worklet = new AudioWorkletNode(
                this.audioContext,
                "audio-processor",
                {
                    numberOfInputs: 1,
                    numberOfOutputs: 1,
                    channelCount: 1
                }
            );

            this.worklet.port.onmessage = (event) => {
                this.handleAudio(event.data);
            };

            this.worklet.onprocessorerror = () => {
                this.handleError("Audio processor error");
            };

            const silentGain =
                this.audioContext.createGain();

            silentGain.gain.value = 0;

            this.source.connect(this.worklet);
            this.worklet.connect(silentGain);
            silentGain.connect(
                this.audioContext.destination
            );

            await websocketService.connect();

            websocketService.onMessage((data) => {
                this.handleServerMessage(data);
            });

            if (this.audioContext.state === "suspended") {
                await this.audioContext.resume();
            }

            this.buffer = [];
            this.bufferSamples = 0;
            this.chunkId = 0;
            this.callStartTime = performance.now();

            this.running = true;

            websocketService.sendJson({
                type: "start",
                sample_rate: this.audioContext.sampleRate,
                channels: 1,
                format: "pcm_f32le",
                chunk_duration_ms: this.chunkDurationMs
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
            samples = new Float32Array(samples);
        }

        this.buffer.push(samples);
        this.bufferSamples += samples.length;

        const requiredSamples = Math.floor(
            this.audioContext.sampleRate *
            this.chunkDurationMs /
            1000
        );

        while (this.bufferSamples >= requiredSamples) {
            const chunk =
                this.extractSamples(requiredSamples);

            this.sendChunk(chunk);
        }
    }

    extractSamples(requiredSamples) {
        const output =
            new Float32Array(requiredSamples);

        let offset = 0;

        while (
            offset < requiredSamples &&
            this.buffer.length > 0
        ) {
            const current = this.buffer[0];

            const copyLength = Math.min(
                current.length,
                requiredSamples - offset
            );

            output.set(
                current.subarray(0, copyLength),
                offset
            );

            offset += copyLength;
            this.bufferSamples -= copyLength;

            if (copyLength === current.length) {
                this.buffer.shift();
            } else {
                this.buffer[0] =
                    current.subarray(copyLength);
            }
        }

        return output;
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

        const timestamp = Math.round(
            performance.now() -
            this.callStartTime
        );

        const metadata = {
            type: "audio",
            chunk_id: this.chunkId,
            timestamp_ms: timestamp,
            duration_ms: this.chunkDurationMs,
            sample_rate: this.audioContext.sampleRate,
            channels: 1,
            format: "pcm_f32le",
            samples: samples.length
        };

        websocketService.sendJson(metadata);

        const audioBuffer = samples.buffer.slice(
            samples.byteOffset,
            samples.byteOffset +
            samples.byteLength
        );

        websocketService.sendBinary(audioBuffer);

        this.onChunk({
            id: this.chunkId,
            timestamp: timestamp,
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

            if (result?.type === "result" || result?.type === "error") {
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
        if (!this.running && !this.stream) {
            return;
        }

        this.stopping = true;
        this.running = false;

        if (this.worklet) {
            this.worklet.port.postMessage({
                type: "stop"
            });

            this.worklet.disconnect();
            this.worklet = null;
        }

        if (this.source) {
            this.source.disconnect();
            this.source = null;
        }

        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }

        if (this.stream) {
            this.stream
                .getTracks()
                .forEach((track) => track.stop());

            this.stream = null;
        }

        if (websocketService.isOpen()) {
            websocketService.sendJson({
                type: "stop"
            });
        }

        websocketService.close();

        this.buffer = [];
        this.bufferSamples = 0;

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