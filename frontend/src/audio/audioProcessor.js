class AudioProcessor extends AudioWorkletProcessor {
    constructor() {
        super();

        this.running = true;

        // ==========================================
        // AUDIO SETTINGS
        // ==========================================

        // 20 ms frame
        this.frameSize = Math.round(sampleRate * 0.02);

        // FFT size
        this.fftSize = 512;

        // ==========================================
        // HAMMING WINDOW
        // ==========================================

        this.window = new Float32Array(this.frameSize);

        for (let i = 0; i < this.frameSize; i++) {
            this.window[i] =
                0.54 -
                0.46 *
                    Math.cos(
                        (2 * Math.PI * i) /
                        (this.frameSize - 1)
                    );
        }

        // ==========================================
        // FRAME BUFFER
        // ==========================================

        this.frameBuffer = new Float32Array(
            this.frameSize
        );

        this.frameIndex = 0;

        // ==========================================
        // VAD
        // ==========================================

        this.minSpeechFrames = 3;
        this.minSilenceFrames = 5;

        this.speechFrames = 0;
        this.silenceFrames = 0;

        this.isSpeech = false;

        // ==========================================
        // NOISE ESTIMATION
        // ==========================================

        this.noiseSpectrum = new Float32Array(
            this.fftSize / 2 + 1
        );

        this.noiseEnergy = 0.00001;

        this.noiseFrames = 0;

        // Maximum number of noise frames
        this.maxNoiseFrames = 50;

        // ==========================================
        // NOISE SUPPRESSION
        // ==========================================

        this.suppressionFactor = 0.15;

        // Never completely remove a frequency bin
        this.minGain = 0.15;

        // ==========================================
        // INITIAL NOISE BOOTSTRAP
        // ==========================================

        /*
         * We need some initial background estimate
         * before VAD becomes reliable.
         *
         * Only very-low-energy frames are accepted
         * during this bootstrap period.
         */
        this.bootstrapFrames = 0;
        this.maxBootstrapFrames = 20;

        // ==========================================
        // STOP MESSAGE
        // ==========================================

        this.port.onmessage = (event) => {
            if (event.data?.type === "stop") {
                this.running = false;
            }
        };
    }

    // ==========================================
    // SHORT-TIME ENERGY
    // ==========================================

    calculateSTE(frame) {
        let energy = 0;

        for (let i = 0; i < frame.length; i++) {
            energy += frame[i] * frame[i];
        }

        return energy / frame.length;
    }

    // ==========================================
    // HAMMING WINDOW
    // ==========================================

    applyHamming(frame) {
        const real = new Float32Array(
            this.fftSize
        );

        for (let i = 0; i < this.frameSize; i++) {
            real[i] =
                frame[i] *
                this.window[i];
        }

        return real;
    }

    // ==========================================
    // FFT
    // ==========================================

    fft(input) {
        const N = input.length;

        const real = new Float32Array(N);
        const imag = new Float32Array(N);

        real.set(input);

        // Bit reversal
        let j = 0;

        for (let i = 1; i < N; i++) {
            let bit = N >> 1;

            while (j & bit) {
                j ^= bit;
                bit >>= 1;
            }

            j ^= bit;

            if (i < j) {
                const temp = real[i];

                real[i] = real[j];
                real[j] = temp;
            }
        }

        // Radix-2 FFT
        for (
            let length = 2;
            length <= N;
            length <<= 1
        ) {
            const angle =
                (-2 * Math.PI) / length;

            const wReal = Math.cos(angle);
            const wImag = Math.sin(angle);

            const half = length >> 1;

            for (
                let i = 0;
                i < N;
                i += length
            ) {
                let currentReal = 1;
                let currentImag = 0;

                for (
                    let k = 0;
                    k < half;
                    k++
                ) {
                    const evenIndex = i + k;
                    const oddIndex =
                        i + k + half;

                    const oddReal =
                        real[oddIndex];

                    const oddImag =
                        imag[oddIndex];

                    const tempReal =
                        currentReal *
                            oddReal -
                        currentImag *
                            oddImag;

                    const tempImag =
                        currentReal *
                            oddImag +
                        currentImag *
                            oddReal;

                    const evenReal =
                        real[evenIndex];

                    const evenImag =
                        imag[evenIndex];

                    real[evenIndex] =
                        evenReal +
                        tempReal;

                    imag[evenIndex] =
                        evenImag +
                        tempImag;

                    real[oddIndex] =
                        evenReal -
                        tempReal;

                    imag[oddIndex] =
                        evenImag -
                        tempImag;

                    const nextReal =
                        currentReal *
                            wReal -
                        currentImag *
                            wImag;

                    currentImag =
                        currentReal *
                            wImag +
                        currentImag *
                            wReal;

                    currentReal =
                        nextReal;
                }
            }
        }

        return {
            real,
            imag
        };
    }

    // ==========================================
    // INVERSE FFT
    // ==========================================

    inverseFFT(real, imag) {
        const N = real.length;

        const inputReal =
            new Float32Array(real);

        const inputImag =
            new Float32Array(imag);

        // Conjugate
        for (let i = 0; i < N; i++) {
            inputImag[i] =
                -inputImag[i];
        }

        const result =
            this.fft(inputReal);

        const output =
            new Float32Array(N);

        for (let i = 0; i < N; i++) {
            output[i] =
                result.real[i] / N;
        }

        return output;
    }

    // ==========================================
    // SPECTRAL FLATNESS
    // ==========================================

    calculateSpectralFlatness(real, imag) {
        let logSum = 0;
        let arithmeticSum = 0;

        const bins =
            this.fftSize / 2 + 1;

        const epsilon = 1e-12;

        for (let i = 1; i < bins; i++) {
            const power =
                real[i] * real[i] +
                imag[i] * imag[i] +
                epsilon;

            logSum += Math.log(power);
            arithmeticSum += power;
        }

        const count = bins - 1;

        const geometricMean =
            Math.exp(
                logSum / count
            );

        const arithmeticMean =
            arithmeticSum / count;

        return (
            geometricMean /
            (arithmeticMean + epsilon)
        );
    }

    // ==========================================
    // MAGNITUDE
    // ==========================================

    calculateMagnitude(real, imag) {
        const magnitude =
            new Float32Array(
                this.fftSize / 2 + 1
            );

        for (
            let i = 0;
            i <= this.fftSize / 2;
            i++
        ) {
            magnitude[i] =
                Math.sqrt(
                    real[i] * real[i] +
                    imag[i] * imag[i]
                );
        }

        return magnitude;
    }

    // ==========================================
    // UPDATE NOISE SPECTRUM
    // ==========================================

    updateNoiseSpectrum(
        magnitude,
        ste
    ) {
        const alpha = 0.9;

        for (
            let i = 0;
            i < magnitude.length;
            i++
        ) {
            this.noiseSpectrum[i] =
                alpha *
                    this.noiseSpectrum[i] +
                (1 - alpha) *
                    magnitude[i];
        }

        this.noiseEnergy =
            alpha * this.noiseEnergy +
            (1 - alpha) * ste;

        this.noiseFrames++;
    }

    // ==========================================
    // NOISE SUPPRESSION
    // ==========================================

    suppressNoise(real, imag) {
        const bins =
            this.fftSize / 2 + 1;

        for (
            let i = 0;
            i < bins;
            i++
        ) {
            const magnitude =
                Math.sqrt(
                    real[i] * real[i] +
                    imag[i] * imag[i]
                );

            const noise =
                this.noiseSpectrum[i];

            if (magnitude < 1e-8) {
                real[i] = 0;
                imag[i] = 0;
                continue;
            }

            /*
             * Spectral subtraction:
             *
             * remaining =
             * signal - estimated noise
             */

            const remaining =
                magnitude -
                this.suppressionFactor *
                    noise;

            let gain =
                remaining /
                magnitude;

            // Limit gain
            gain = Math.max(
                this.minGain,
                Math.min(1, gain)
            );

            real[i] *= gain;
            imag[i] *= gain;

            /*
             * Mirror positive-frequency
             * bins to negative-frequency bins.
             */
            if (
                i > 0 &&
                i < this.fftSize / 2
            ) {
                const mirror =
                    this.fftSize - i;

                real[mirror] =
                    real[i];

                imag[mirror] =
                    -imag[i];
            }
        }

        return {
            real,
            imag
        };
    }

    // ==========================================
    // VAD
    // ==========================================

    updateVAD(
        ste,
        flatness
    ) {
        /*
         * Compare current energy against
         * estimated background energy.
         */
        const energyThreshold =
            Math.max(
                0.00001,
                this.noiseEnergy * 2.0
            );

        const energySpeech =
            ste > energyThreshold;

        /*
         * High spectral flatness is
         * generally more noise-like.
         */
        const noiseLike =
            flatness > 0.85;

        const speechDetected =
            energySpeech &&
            !noiseLike;

        if (speechDetected) {
            this.speechFrames++;
            this.silenceFrames = 0;

            if (
                this.speechFrames >=
                this.minSpeechFrames
            ) {
                this.isSpeech = true;
            }
        } else {
            this.silenceFrames++;
            this.speechFrames = 0;

            if (
                this.silenceFrames >=
                this.minSilenceFrames
            ) {
                this.isSpeech = false;
            }
        }
    }

    // ==========================================
    // ANALYZE + SUPPRESS
    // ==========================================

    analyzeAndSuppress(frame) {
        // Short-Time Energy
        const ste =
            this.calculateSTE(frame);

        // Hamming window
        const windowed =
            this.applyHamming(frame);

        // FFT
        const spectrum =
            this.fft(windowed);

        // Spectral flatness
        const flatness =
            this.calculateSpectralFlatness(
                spectrum.real,
                spectrum.imag
            );

        // Magnitude spectrum
        const magnitude =
            this.calculateMagnitude(
                spectrum.real,
                spectrum.imag
            );

        /*
         * Update VAD first using the
         * current frame.
         */
        this.updateVAD(
            ste,
            flatness
        );

        /*
         * ======================================
         * NOISE ESTIMATION
         * ======================================
         *
         * IMPORTANT:
         *
         * We no longer assume that the first
         * 20 frames are automatically noise.
         *
         * Noise is learned only when the frame
         * is classified as non-speech.
         */

        if (
            !this.isSpeech &&
            this.noiseFrames <
                this.maxNoiseFrames
        ) {
            this.updateNoiseSpectrum(
                magnitude,
                ste
            );
        }

        /*
         * During the very beginning, VAD may
         * not yet be reliable.
         *
         * Only use extremely low-energy
         * frames for initial bootstrapping.
         */
        if (
            this.noiseFrames === 0 &&
            this.bootstrapFrames <
                this.maxBootstrapFrames
        ) {
            const bootstrapThreshold =
                0.0001;

            if (
                ste <
                bootstrapThreshold
            ) {
                this.updateNoiseSpectrum(
                    magnitude,
                    ste
                );

                this.bootstrapFrames++;
            }
        }

        // Suppress noise
        const cleaned =
            this.suppressNoise(
                spectrum.real,
                spectrum.imag
            );

        // Inverse FFT
        const reconstructed =
            this.inverseFFT(
                cleaned.real,
                cleaned.imag
            );

        /*
         * Keep only the actual
         * 20 ms frame.
         */
        const output =
            new Float32Array(
                this.frameSize
            );

        for (
            let i = 0;
            i < this.frameSize;
            i++
        ) {
            output[i] =
                reconstructed[i];
        }

        return {
            cleaned: output,
            ste,
            flatness
        };
    }

    // ==========================================
    // AUDIO PROCESSOR
    // ==========================================

    process(inputs) {
        if (!this.running) {
            return false;
        }

        const input = inputs[0];

        if (
            !input ||
            input.length === 0
        ) {
            return true;
        }

        const channelCount =
            input.length;

        const frameCount =
            input[0]?.length;

        if (!frameCount) {
            return true;
        }

        // ======================================
        // CONVERT TO MONO
        // ======================================

        const samples =
            new Float32Array(
                frameCount
            );

        if (channelCount === 1) {
            samples.set(input[0]);
        } else {
            for (
                let i = 0;
                i < frameCount;
                i++
            ) {
                let sum = 0;

                for (
                    let channel = 0;
                    channel < channelCount;
                    channel++
                ) {
                    sum +=
                        input[channel][i];
                }

                samples[i] =
                    sum / channelCount;
            }
        }

        // ======================================
        // PROCESS 20 ms FRAMES
        // ======================================

        const cleanedOutput =
            new Float32Array(
                samples.length
            );

        let outputIndex = 0;

        for (
            let i = 0;
            i < samples.length;
            i++
        ) {
            this.frameBuffer[
                this.frameIndex
            ] = samples[i];

            this.frameIndex++;

            if (
                this.frameIndex ===
                this.frameSize
            ) {
                const result =
                    this.analyzeAndSuppress(
                        this.frameBuffer
                    );

                cleanedOutput.set(
                    result.cleaned,
                    outputIndex
                );

                outputIndex +=
                    this.frameSize;

                this.frameIndex = 0;
            }
        }

        // ======================================
        // SEND CLEANED AUDIO
        // ======================================

        if (outputIndex > 0) {
            const output =
                cleanedOutput.slice(
                    0,
                    outputIndex
                );

            this.port.postMessage(
                {
                    samples: output,
                    isSpeech:
                        this.isSpeech
                },
                [output.buffer]
            );
        }

        return true;
    }
}

// ==========================================
// REGISTER PROCESSOR
// ==========================================

registerProcessor(
    "audio-processor",
    AudioProcessor
);