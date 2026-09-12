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

        this.requiredSamples = Math.round(
            this.sampleRate *
            this.chunkDurationMs /
            1000
        );

        this.chunkId = 0;
        this.callStartTime = 0;

        this.speechFrames = 0;
        this.totalFrames = 0;

        this.running = false;
        this.stopping = false;
        this.messageHandler = null;
    }

    async start() {
        if (this.running) return;

        try {
            this.stopping = false;

            this.onStatus(
                "Requesting microphone..."
            );

            this.stream =
                await navigator.mediaDevices
                    .getUserMedia({
                        audio: {
                            channelCount: 1,
                            sampleRate:
                                this.sampleRate,

                            echoCancellation: true,

                            noiseSuppression: true,

                            autoGainControl: false
                        }
                    });

            this.audioContext =
                new AudioContext({
                    sampleRate:
                        this.sampleRate,
                    latencyHint:
                        "interactive"
                });

            if (
                this.audioContext.sampleRate !==
                this.sampleRate
            ) {
                throw new Error(
                    `Unsupported sample rate: ${this.audioContext.sampleRate} Hz`
                );
            }

            await this.audioContext
                .audioWorklet
                .addModule(
                    new URL(
                        "./audioProcessor.js",
                        import.meta.url
                    )
                );

            this.source =
                this.audioContext
                    .createMediaStreamSource(
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
                        channelCountMode:
                            "explicit",
                        channelInterpretation:
                            "speakers"
                    }
                );

            this.worklet.port.onmessage =
                (event) => {
                    this.handleAudio(
                        event.data
                    );
                };

            this.worklet.onprocessorerror =
                () => {
                    this.handleError(
                        "Audio processor error"
                    );
                };

            this.silentGain =
                this.audioContext
                    .createGain();

            this.silentGain.gain.value = 0;

            this.source.connect(
                this.worklet
            );

            this.worklet.connect(
                this.silentGain
            );

            this.silentGain.connect(
                this.audioContext
                    .destination
            );

            await websocketService.connect();

            this.messageHandler =
                (data) => {
                    this.handleServerMessage(
                        data
                    );
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

            this.buffer =
                new Float32Array(0);

            this.bufferSamples = 0;

            this.chunkId = 0;

            this.speechFrames = 0;
            this.totalFrames = 0;

            this.callStartTime =
                performance.now();

            this.running = true;

            websocketService.sendJson({
                type: "start",

                sample_rate:
                    this.sampleRate,

                channels: 1,

                format:
                    "wav",

                encoding:
                    "pcm_s16le",

                chunk_duration_ms:
                    this.chunkDurationMs
            });

            this.onStatus(
                "Recording"
            );

        } catch (error) {
            this.handleError(error);
        }
    }

    handleAudio(data) {
        if (!this.running) return;

        if (
            !data ||
            !data.samples
        ) {
            return;
        }

        let samples =
            data.samples;

        if (
            !(samples instanceof
                Float32Array)
        ) {
            samples =
                new Float32Array(
                    samples
                );
        }

        if (samples.length === 0) {
            return;
        }

        /*
         * These samples are already
         * noise-suppressed by
         * audioProcessor.js.
         */

        if (data.isSpeech) {
            this.speechFrames++;
        }

        this.totalFrames++;

        /*
         * Add cleaned samples
         * to the 4-second buffer.
         */

        const combined =
            new Float32Array(
                this.bufferSamples +
                samples.length
            );

        combined.set(
            this.buffer
        );

        combined.set(
            samples,
            this.bufferSamples
        );

        this.buffer = combined;

        this.bufferSamples =
            combined.length;

        /*
         * Send exact 4-second chunks.
         */

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

            const speechRatio =
                this.totalFrames > 0
                    ? this.speechFrames /
                      this.totalFrames
                    : 0;

            this.sendChunk(
                chunk,
                speechRatio
            );

            this.speechFrames = 0;
            this.totalFrames = 0;
        }
    }

    createWav(samples) {
        const numChannels = 1;
        const bitsPerSample = 16;
        const bytesPerSample = 2;

        const dataSize =
            samples.length *
            bytesPerSample;

        const buffer =
            new ArrayBuffer(
                44 + dataSize
            );

        const view =
            new DataView(buffer);

        /*
         * RIFF header
         */

        view.setUint8(0, "R".charCodeAt(0));
        view.setUint8(1, "I".charCodeAt(0));
        view.setUint8(2, "F".charCodeAt(0));
        view.setUint8(3, "F".charCodeAt(0));

        view.setUint32(
            4,
            36 + dataSize,
            true
        );

        /*
         * WAVE
         */

        view.setUint8(8, "W".charCodeAt(0));
        view.setUint8(9, "A".charCodeAt(0));
        view.setUint8(10, "V".charCodeAt(0));
        view.setUint8(11, "E".charCodeAt(0));

        /*
         * fmt chunk
         */

        view.setUint8(12, "f".charCodeAt(0));
        view.setUint8(13, "m".charCodeAt(0));
        view.setUint8(14, "t".charCodeAt(0));
        view.setUint8(15, " ".charCodeAt(0));

        view.setUint32(
            16,
            16,
            true
        );

        view.setUint16(
            20,
            1,
            true
        );

        view.setUint16(
            22,
            numChannels,
            true
        );

        view.setUint32(
            24,
            this.sampleRate,
            true
        );

        view.setUint32(
            28,
            this.sampleRate *
            numChannels *
            bytesPerSample,
            true
        );

        view.setUint16(
            32,
            numChannels *
            bytesPerSample,
            true
        );

        view.setUint16(
            34,
            bitsPerSample,
            true
        );

        /*
         * data chunk
         */

        view.setUint8(36, "d".charCodeAt(0));
        view.setUint8(37, "a".charCodeAt(0));
        view.setUint8(38, "t".charCodeAt(0));
        view.setUint8(39, "a".charCodeAt(0));

        view.setUint32(
            40,
            dataSize,
            true
        );

        /*
         * Float32 -> PCM 16-bit
         */

        let offset = 44;

        for (
            let i = 0;
            i < samples.length;
            i++
        ) {
            let sample = samples[i];

            sample =
                Math.max(
                    -1,
                    Math.min(
                        1,
                        sample
                    )
                );

            const pcm =
                sample < 0
                    ? sample * 32768
                    : sample * 32767;

            view.setInt16(
                offset,
                pcm,
                true
            );

            offset += 2;
        }

        return buffer;
    }

    sendChunk(
        samples,
        speechRatio
    ) {
        if (!this.running) return;

        if (
            !websocketService.isOpen()
        ) {
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

        /*
         * Convert cleaned Float32
         * samples into WAV.
         */

        const wavBuffer =
            this.createWav(
                samples
            );

        const metadata = {
            type: "audio",

            chunk_id:
                this.chunkId,

            timestamp_ms:
                timestamp,

            duration_ms:
                this.chunkDurationMs,

            sample_rate:
                this.sampleRate,

            channels: 1,

            format:
                "wav",

            encoding:
                "pcm_s16le",

            samples:
                samples.length,

            speech_ratio:
                Number(
                    speechRatio.toFixed(3)
                ),

            byte_length:
                wavBuffer.byteLength
        };

        websocketService.sendJson(
            metadata
        );

        /*
         * Send the CLEANED WAV.
         */

        websocketService.sendBinary(
            wavBuffer
        );

        this.onChunk({
            id:
                this.chunkId,

            timestamp,

            duration:
                this.chunkDurationMs,

            samples:
                samples.length,

            speechRatio:
                Number(
                    speechRatio.toFixed(3)
                )
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
                this.onResult(
                    result
                );
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

            this.worklet.port.onmessage =
                null;

            this.worklet.onprocessorerror =
                null;

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
                .forEach((track) =>
                    track.stop()
                );

            this.stream = null;
        }

        if (
            websocketService.isOpen()
        ) {
            websocketService.sendJson({
                type: "stop"
            });

            websocketService.close();
        }

        this.buffer =
            new Float32Array(0);

        this.bufferSamples = 0;

        this.chunkId = 0;

        this.speechFrames = 0;
        this.totalFrames = 0;

        this.onStatus(
            "Stopped"
        );
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