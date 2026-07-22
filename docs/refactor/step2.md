Implement the Shimmer DSP foundation.

Primary goal:
Protect the low/mid body of the song and only send the high-frequency band into artifact cleaning.

Requirements:

1. Add or refactor core DSP utilities to ensure audio is represented internally as channels-first stereo:
   shape = (2, samples)

2. Implement a perfect-reconstruction linear-phase FIR crossover using spectral inversion:
   - Default crossover: 4500 Hz
   - Allow config for 5000 Hz
   - numtaps: 1023
   - Odd tap count only
   - Use scipy.signal.firwin for the lowpass
   - Create the highpass using spectral inversion:
     fir_high = -fir_low
     fir_high[delay] += 1.0

3. Do not use np.roll anywhere for delay compensation.

4. Do not use two independently designed lowpass/highpass filters.

5. Do not use filtfilt for the crossover unless you can prove complementary reconstruction is preserved. Prefer aligned FFT convolution or direct convolution with exact delay trimming.

6. Implement:
   - ensure_stereo_channels_first()
   - complementary_fir_split()
   - encode_ms()
   - decode_ms()
   - recombine_bands()
   - null_test_split_recombine()

7. The dry split and recombination must null against the original signal within floating-point tolerance:
   low_band + high_band ≈ original

8. Add or update tests proving:
   - Mono input becomes dual-mono stereo
   - Stereo input remains stereo
   - Split/recombine reconstructs accurately
   - No circular wraparound occurs
   - Output length equals input length
   - M/S encode/decode reconstructs accurately

Be conservative. Preserve existing public APIs where possible, but add wrappers if needed.