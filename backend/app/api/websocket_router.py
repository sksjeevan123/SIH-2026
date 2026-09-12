async def process_audio_chunk(call_id: str, data: np.ndarray, sr: int):
    if len(data.shape) > 1:
        data = data.mean(axis=1)

    if call_id not in stream_buffer.active_buffers:
        stream_buffer.active_buffers[call_id] = []
    stream_buffer.active_buffers[call_id].append(data)
    continuous_audio = stream_buffer.active_buffers[call_id][-1]

    clean_audio, prosody_metrics = vad_filter.extract_speech_and_metrics(
        continuous_audio, samplerate=sr
    )

    if clean_audio is None:
        return {"status": "filtered", "message": "No active speech detected."}

    # Compute MFCC/F0/CQT once, reuse for both the reported feature-matrix
    # shape and the ensemble ML scoring
    components = feature_extractor.extract_components(clean_audio)
    feature_matrix = feature_extractor.extract_and_stack(clean_audio, components=components)

    ml_result = await analyze_voice_authenticity(
        clean_audio, sample_rate=sr, feature_components=components
    )

    return {
        "status": "success",
        "message": "Authenticated and processed successfully.",
        "feature_matrix_shape": list(feature_matrix.shape),
        "prosody_metrics": prosody_metrics,
        "ml_inference": ml_result,
    }