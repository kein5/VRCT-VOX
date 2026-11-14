//! The input high-pass filter (specification section 4): a fifth-order Butterworth at
//! 48 Hz applied forward and backward so that it adds no phase shift.

/// Transfer function coefficients, highest power first, `a[0] == 1`.
#[derive(Debug, Clone, PartialEq)]
pub struct Coefficients {
    pub b: Vec<f64>,
    pub a: Vec<f64>,
}

#[derive(Clone, Copy)]
struct Complex(f64, f64);

impl Complex {
    fn mul(self, other: Complex) -> Complex {
        Complex(self.0 * other.0 - self.1 * other.1, self.0 * other.1 + self.1 * other.0)
    }

    fn div(self, other: Complex) -> Complex {
        let norm = other.0 * other.0 + other.1 * other.1;
        Complex((self.0 * other.0 + self.1 * other.1) / norm, (self.1 * other.0 - self.0 * other.1) / norm)
    }
}

/// Designs a digital Butterworth high-pass filter with the bilinear transform.
pub fn butterworth_highpass(order: usize, cutoff_hz: f64, sample_rate: f64) -> Coefficients {
    // Work at a nominal sampling rate of 2 with a pre-warped cutoff, the usual convention.
    let rate = 2.0;
    let warped = 2.0 * rate * (std::f64::consts::PI * cutoff_hz / sample_rate).tan();
    let double_rate = 2.0 * rate;
    let mut poles = Vec::with_capacity(order);
    let mut gain = Complex(1.0, 0.0);
    for k in 0..order {
        // Unit-circle prototype pole in the left half plane, mapped low-pass -> high-pass
        // (s -> warped / s) and then onto the z plane.
        let angle = std::f64::consts::PI * (2 * k + order + 1) as f64 / (2 * order) as f64;
        let prototype = Complex(angle.cos(), angle.sin());
        let analog = Complex(warped, 0.0).div(prototype);
        poles.push(Complex(double_rate + analog.0, analog.1).div(Complex(double_rate - analog.0, -analog.1)));
        // Each analog zero at the origin maps to z = 1 and contributes 2*rate to the gain.
        gain = gain.mul(Complex(double_rate, 0.0).div(Complex(double_rate - analog.0, -analog.1)));
    }
    let expand = |roots: &[Complex]| {
        let mut poly = vec![Complex(1.0, 0.0)];
        for &root in roots {
            let mut next = vec![Complex(0.0, 0.0); poly.len() + 1];
            for (index, &term) in poly.iter().enumerate() {
                next[index].0 += term.0;
                next[index].1 += term.1;
                let scaled = term.mul(root);
                next[index + 1].0 -= scaled.0;
                next[index + 1].1 -= scaled.1;
            }
            poly = next;
        }
        poly.into_iter().map(|term| term.0).collect::<Vec<f64>>()
    };
    let zeros = vec![Complex(1.0, 0.0); order];
    let b = expand(&zeros).into_iter().map(|term| term * gain.0).collect();
    Coefficients { b, a: expand(&poles) }
}

/// The filter the pipeline applies to 16 kHz input.
pub fn input_highpass() -> Coefficients {
    butterworth_highpass(5, 48.0, 16_000.0)
}

/// Steady-state filter memory for a unit step input (transposed direct form II).
///
/// The state solves `(I - A) zi = B` for the companion matrix of `a`; summing the
/// equations gives the first element and the rest follow by substitution, which stays
/// accurate even though the system is nearly singular for a cutoff this low.
fn steady_state(coefficients: &Coefficients) -> Vec<f64> {
    let (b, a) = (&coefficients.b, &coefficients.a);
    let n = a.len() - 1;
    let rhs = |k: usize| b[k] - a[k] * b[0];
    let mut state = vec![0.0; n];
    state[0] = (1..=n).map(rhs).sum::<f64>() / a.iter().sum::<f64>();
    let (mut a_sum, mut rhs_sum) = (1.0, 0.0);
    for k in 1..n {
        a_sum += a[k];
        rhs_sum += rhs(k);
        state[k] = a_sum * state[0] - rhs_sum;
    }
    state
}

fn filter_in_place(coefficients: &Coefficients, signal: &mut [f64], state: &mut [f64]) {
    let (b, a) = (&coefficients.b, &coefficients.a);
    let n = state.len();
    for sample in signal.iter_mut() {
        let input = *sample;
        let output = b[0] * input + state[0];
        for k in 0..n - 1 {
            state[k] = b[k + 1] * input + state[k + 1] - a[k + 1] * output;
        }
        state[n - 1] = b[n] * input - a[n] * output;
        *sample = output;
    }
}

/// Zero-phase filtering: forward, then backward, with odd-reflection padding of three
/// filter lengths at each end and the filter started in its steady state.
///
/// Inputs no longer than the padding are returned unchanged.
pub fn filtfilt(coefficients: &Coefficients, signal: &[f64]) -> Vec<f64> {
    let pad = 3 * coefficients.a.len().max(coefficients.b.len());
    if signal.len() <= pad {
        return signal.to_vec();
    }
    let (first, last) = (signal[0], signal[signal.len() - 1]);
    let mut extended = Vec::with_capacity(signal.len() + 2 * pad);
    extended.extend((1..=pad).rev().map(|k| 2.0 * first - signal[k]));
    extended.extend_from_slice(signal);
    extended.extend((1..=pad).map(|k| 2.0 * last - signal[signal.len() - 1 - k]));
    let steady = steady_state(coefficients);
    for _ in 0..2 {
        let mut state: Vec<f64> = steady.iter().map(|value| value * extended[0]).collect();
        filter_in_place(coefficients, &mut extended, &mut state);
        extended.reverse();
    }
    extended[pad..pad + signal.len()].to_vec()
}

#[cfg(test)]
mod tests {
    use super::*;

    // scipy.signal.butter(N=5, Wn=48, btype="high", fs=16000), SciPy 1.13.1.
    const B: [f64; 6] = [0.9699606451838447, -4.849803225919223, 9.699606451838447, -9.699606451838447, 4.849803225919223, -0.9699606451838447];
    const A: [f64; 6] = [1.0, -4.939001819168364, 9.757863526739543, -9.639544849413458, 4.761506797356209, -0.9408236532054606];
    const EXPECTED: [(usize, f64); 6] = [
        (0, -0.16470803800367345),
        (1, -0.23321293192826786),
        (17, -0.058708146378604865),
        (32, 0.18250219086844616),
        (62, -0.14122273709364574),
        (63, -0.10271743819875212),
    ];

    #[test]
    fn design_matches_the_reference_coefficients() {
        let designed = input_highpass();
        for (found, expected) in designed.b.iter().zip(B).chain(designed.a.iter().zip(A)) {
            assert!((found - expected).abs() < 1e-11, "{found} vs {expected}");
        }
    }

    #[test]
    fn filtfilt_matches_the_reference_output() {
        // x[n] = sin(0.05 n) + 0.3 cos(0.9 n) + 0.5, n = 0..63; scipy.signal.filtfilt(b, a, x).
        let signal: Vec<f64> = (0..64).map(|n| (0.05 * n as f64).sin() + 0.3 * (0.9 * n as f64).cos() + 0.5).collect();
        let filtered = filtfilt(&Coefficients { b: B.to_vec(), a: A.to_vec() }, &signal);
        for (index, expected) in EXPECTED {
            // The steady-state start divides by 1 + sum(a[1..]), about 1e-9 here, so the
            // edges are only reproducible to roughly 1e-7 between implementations.
            assert!((filtered[index] - expected).abs() < 5e-7, "sample {index}: {} vs {expected}", filtered[index]);
        }
    }

    #[test]
    fn short_inputs_pass_through() {
        let signal = vec![0.25; 18];
        assert_eq!(filtfilt(&input_highpass(), &signal), signal);
    }
}
