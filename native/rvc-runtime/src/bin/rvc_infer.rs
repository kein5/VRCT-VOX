//! Offline voice conversion from the command line: WAV in, 16-bit WAV out.

use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Instant;

use rvc_runtime::{audio, Chunking, Converter, Device, FeatureExtractor, FeatureIndex, NoiseMode, Options, Rmvpe, Synthesizer, VoiceModel};

const USAGE: &str = "\
Usage: rvc-infer --model <voice.pth> --hubert <hubert.onnx> --rmvpe <rmvpe.onnx>
                 --input <in.wav> --output <out.wav> [options]

Options:
  --index <file.index>     retrieval index of the voice model
  --index-rate <0..1>      share of retrieved features (default 0.75; needs --index)
  --protect <0..0.5>       protection of unvoiced frames (default 0.33; 0.5 disables)
  --transpose <semitones>  key change (default 0)
  --speaker <n>            speaker number (default 0)
  --rms-mix-rate <0..1>    1 keeps the output loudness (default), lower follows the input
  --resample-sr <hz>       output sample rate (default: the model's)
  --seed <n>               fix the synthesis noise so the output is reproducible
  --device <cpu|cuda>      where the networks run (default cpu)
  --chunk <pad,query,center,max>
                           seconds used to split long input (default 3,10,60,65)
";

struct Arguments {
    model: PathBuf,
    hubert: PathBuf,
    rmvpe: PathBuf,
    input: PathBuf,
    output: PathBuf,
    index: Option<PathBuf>,
    device: Device,
    options: Options,
}

fn parse() -> Result<Arguments, String> {
    let mut values = std::collections::HashMap::new();
    let mut arguments = std::env::args().skip(1);
    while let Some(flag) = arguments.next() {
        let name = flag.strip_prefix("--").ok_or_else(|| format!("unexpected argument `{flag}`"))?.to_string();
        let value = arguments.next().ok_or_else(|| format!("`{flag}` needs a value"))?;
        values.insert(name, value);
    }
    let mut path = |name: &str| values.remove(name).map(PathBuf::from);
    let mut required = |name: &str| path(name).ok_or_else(|| format!("`--{name}` is required"));
    let (model, hubert, rmvpe, input, output) = (required("model")?, required("hubert")?, required("rmvpe")?, required("input")?, required("output")?);
    let index = path("index");
    fn number<T: std::str::FromStr>(values: &mut std::collections::HashMap<String, String>, name: &str, default: T) -> Result<T, String> {
        match values.remove(name) {
            Some(text) => text.parse().map_err(|_| format!("`--{name}` has an invalid value")),
            None => Ok(default),
        }
    }
    let defaults = Options::default();
    let mut options = Options {
        transpose: number(&mut values, "transpose", defaults.transpose)?,
        index_rate: number(&mut values, "index-rate", defaults.index_rate)?,
        protect: number(&mut values, "protect", defaults.protect)?,
        speaker: number(&mut values, "speaker", defaults.speaker)?,
        rms_mix_rate: number(&mut values, "rms-mix-rate", defaults.rms_mix_rate)?,
        resample_sr: number(&mut values, "resample-sr", defaults.resample_sr)?,
        ..defaults
    };
    if let Some(seed) = values.remove("seed") {
        options.noise = NoiseMode::Seeded(seed.parse().map_err(|_| "`--seed` has an invalid value".to_string())?);
    }
    if let Some(chunk) = values.remove("chunk") {
        let parts: Vec<usize> = chunk.split(',').map(|part| part.trim().parse()).collect::<Result<_, _>>().map_err(|_| "`--chunk` has an invalid value".to_string())?;
        let [pad, query, center, max] = parts[..] else { return Err("`--chunk` needs four values".into()) };
        options.chunking = Chunking { pad, query, center, max };
    }
    let device = match values.remove("device").as_deref() {
        None | Some("cpu") => Device::Cpu,
        Some("cuda") => Device::Cuda,
        Some(_) => return Err("`--device` must be cpu or cuda".into()),
    };
    if let Some(unknown) = values.keys().next() {
        return Err(format!("unknown option `--{unknown}`"));
    }
    Ok(Arguments { model, hubert, rmvpe, input, output, index, device, options })
}

fn run(arguments: Arguments) -> rvc_runtime::Result<()> {
    let started = Instant::now();
    let model = VoiceModel::load(&arguments.model)?;
    let index = arguments.index.as_deref().map(FeatureIndex::load).transpose()?;
    let mut converter = Converter {
        features: FeatureExtractor::load(&arguments.hubert, arguments.device)?,
        pitch: Box::new(Rmvpe::load(&arguments.rmvpe, arguments.device)?),
        synthesizer: Synthesizer::new(&model, arguments.device)?,
        index,
        version: model.version,
    };
    let loaded = started.elapsed();
    let (samples, rate) = audio::read_wav(&arguments.input)?;
    let input = audio::resample(&samples, rate, rvc_runtime::pipeline::INPUT_RATE);
    let seconds = input.len() as f64 / rvc_runtime::pipeline::INPUT_RATE as f64;
    let converting = Instant::now();
    let converted = converter.convert(&input, &arguments.options)?;
    let elapsed = converting.elapsed().as_secs_f64();
    audio::write_wav(&arguments.output, &converted.samples, converted.sample_rate, converted.int16_gain)?;
    // Numbers only: nothing about the audio content is printed.
    eprintln!(
        "model {:?} {} Hz f0={} | loaded in {:.2} s | {:.2} s of audio converted in {:.2} s (RTF {:.3}) | output {} Hz",
        model.version,
        model.config.sample_rate,
        model.f0,
        loaded.as_secs_f64(),
        seconds,
        elapsed,
        elapsed / seconds,
        converted.sample_rate
    );
    Ok(())
}

fn main() -> ExitCode {
    let arguments = match parse() {
        Ok(arguments) => arguments,
        Err(message) => {
            eprintln!("{message}\n\n{USAGE}");
            return ExitCode::from(2);
        }
    };
    match run(arguments) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("error: {error}");
            ExitCode::FAILURE
        }
    }
}
