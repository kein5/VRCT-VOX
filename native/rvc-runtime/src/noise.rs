//! The random parts of synthesis, kept outside the network graphs so that a seed makes a
//! conversion reproducible (specification sections 9.2 and 13.2).

/// Where the synthesizer's random numbers come from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NoiseMode {
    /// A fresh seed per conversion (normal use).
    Random,
    /// The same numbers every time for the same seed (verification).
    Seeded(u64),
    /// All noise terms are zero. Not a listening mode: it removes the breath and
    /// consonant noise. It exists to compare the deterministic part of the synthesizer
    /// against the reference sample by sample.
    Zero,
}

/// xoshiro256++ seeded through SplitMix64. Written out here rather than taken from a
/// crate so that a seed keeps meaning the same numbers across dependency updates.
#[derive(Debug, Clone)]
pub struct Generator {
    state: Option<[u64; 4]>,
    spare: Option<f32>,
}

impl Generator {
    pub fn new(mode: NoiseMode) -> Self {
        let seed = match mode {
            NoiseMode::Zero => return Generator { state: None, spare: None },
            NoiseMode::Seeded(seed) => seed,
            NoiseMode::Random => {
                use std::hash::{BuildHasher, Hasher};
                let clock = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |elapsed| elapsed.as_nanos() as u64);
                // RandomState carries per-process entropy from the operating system.
                let mut hasher = std::collections::hash_map::RandomState::new().build_hasher();
                hasher.write_u64(clock);
                hasher.finish()
            }
        };
        let mut mix = seed;
        let mut next = || {
            mix = mix.wrapping_add(0x9e37_79b9_7f4a_7c15);
            let mut z = mix;
            z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
            z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
            z ^ (z >> 31)
        };
        Generator { state: Some([next(), next(), next(), next()]), spare: None }
    }

    fn next_u64(state: &mut [u64; 4]) -> u64 {
        let result = state[0].wrapping_add(state[3]).rotate_left(23).wrapping_add(state[0]);
        let shifted = state[1] << 17;
        state[2] ^= state[0];
        state[3] ^= state[1];
        state[1] ^= state[2];
        state[0] ^= state[3];
        state[2] ^= shifted;
        state[3] = state[3].rotate_left(45);
        result
    }

    /// A standard normal sample (Box-Muller), or zero in [`NoiseMode::Zero`].
    pub fn normal(&mut self) -> f32 {
        let Some(state) = self.state.as_mut() else { return 0.0 };
        if let Some(value) = self.spare.take() {
            return value;
        }
        // Uniform in (0, 1] so the logarithm is finite, and in [0, 1) for the angle.
        let u1 = ((Self::next_u64(state) >> 11) + 1) as f64 / (1u64 << 53) as f64;
        let u2 = (Self::next_u64(state) >> 11) as f64 / (1u64 << 53) as f64;
        let radius = (-2.0 * u1.ln()).sqrt();
        let angle = 2.0 * std::f64::consts::PI * u2;
        self.spare = Some((radius * angle.sin()) as f32);
        (radius * angle.cos()) as f32
    }

    pub fn normals(&mut self, count: usize) -> Vec<f32> {
        (0..count).map(|_| self.normal()).collect()
    }
}

const SINE_AMPLITUDE: f32 = 0.1;
const VOICED_NOISE: f32 = 0.003;

/// The NSF excitation for one F0 track: a sine at the pitch where voiced, noise elsewhere.
///
/// `f0` is in Hz per 10 ms frame and each frame becomes `samples_per_frame` samples.
/// Within a frame the phase advances at that frame's F0; the phase reached at the end of
/// a frame carries into the next one so the sine stays continuous across frames. Voiced
/// samples get a little noise on top, unvoiced samples are noise of a third of the sine
/// amplitude.
pub fn excitation(f0: &[f32], samples_per_frame: usize, sample_rate: u32, generator: &mut Generator) -> Vec<f32> {
    let mut output = Vec::with_capacity(f0.len() * samples_per_frame);
    let (mut carried, mut turns) = (0.0f32, 0.0f32);
    for &hz in f0 {
        let step = hz / sample_rate as f32;
        let voiced = hz > 0.0;
        for n in 1..=samples_per_frame {
            let phase = step * n as f32 + carried;
            let noise = generator.normal();
            output.push(if voiced {
                (2.0 * std::f32::consts::PI * phase).sin() * SINE_AMPLITUDE + VOICED_NOISE * noise
            } else {
                SINE_AMPLITUDE / 3.0 * noise
            });
        }
        // Carry the phase reached at the frame end: each frame contributes its own advance
        // wrapped to [-0.5, 0.5), and the running total is taken modulo one cycle.
        let end = step * samples_per_frame as f32;
        turns += (end + 0.5) % 1.0 - 0.5;
        carried = turns % 1.0;
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_seed_reproduces_the_same_numbers() {
        let first = Generator::new(NoiseMode::Seeded(42)).normals(1000);
        assert_eq!(first, Generator::new(NoiseMode::Seeded(42)).normals(1000));
        assert_ne!(first, Generator::new(NoiseMode::Seeded(43)).normals(1000));
        // Pinned so that a seed keeps meaning the same noise in later versions.
        assert_eq!(&first[..3], &PINNED);
    }

    const PINNED: [f32; 3] = [-0.26860738, 0.58197105, -0.05446217];

    #[test]
    fn samples_look_standard_normal() {
        let samples = Generator::new(NoiseMode::Seeded(1)).normals(200_000);
        let mean = samples.iter().sum::<f32>() / samples.len() as f32;
        let variance = samples.iter().map(|x| (x - mean) * (x - mean)).sum::<f32>() / samples.len() as f32;
        assert!(mean.abs() < 0.01, "mean {mean}");
        assert!((variance - 1.0).abs() < 0.02, "variance {variance}");
    }

    #[test]
    fn zero_mode_is_silent_where_unvoiced_and_a_pure_sine_where_voiced() {
        let mut generator = Generator::new(NoiseMode::Zero);
        let wave = excitation(&[0.0, 100.0, 100.0], 400, 40_000, &mut generator);
        assert!(wave[..400].iter().all(|&x| x == 0.0));
        // 100 Hz at 40 kHz: one cycle per 400 samples, so the second voiced frame repeats the first.
        for n in 0..400 {
            let expected = (2.0 * std::f32::consts::PI * (n + 1) as f32 / 400.0).sin() * 0.1;
            assert!((wave[400 + n] - expected).abs() < 1e-6);
            assert!((wave[800 + n] - expected).abs() < 1e-5);
        }
    }

    #[test]
    fn phase_is_continuous_across_frames() {
        let mut generator = Generator::new(NoiseMode::Zero);
        let wave = excitation(&[110.0, 113.0, 220.0], 480, 48_000, &mut generator);
        // The largest step of a 220 Hz sine of amplitude 0.1 at 48 kHz is about 0.0029.
        for pair in wave.windows(2) {
            assert!((pair[1] - pair[0]).abs() < 0.004);
        }
    }
}
