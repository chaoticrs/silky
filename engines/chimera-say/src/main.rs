//! chimera-say <cmudict.txt.gz>
//!
//! Contract (one JSON object per line on stdin, one JSON reply per line on stdout):
//!   in : {"text": "...", "out": "file.wav", "female": 0..1, "child": 0..1, "f0": Hz, "rate": x,
//!         "accent": x, "source": {"breathiness", "tension", "roughness", "fry", "brightness",
//!         "vibratoDepth", "vibratoRate", "pressure", "drift"}}      (everything but text/out optional)
//!         "motion": "file.json" also writes what the voice's body did, for a display to replay:
//!           {"fps": frames per second, "body": {"female", "child"}, "frames": [engine telemetry snapshot, ...]}
//!           (snapshots as the engine serialises VoiceTelemetry, numbers to 4 decimals, glottal scopes thinned)
//!   out: {"ok": true, "seconds": audio length, "ms": render time}  or  {"ok": false, "error": "..."}
//! The WAV is 48 kHz mono 16-bit. The dictionary is loaded once, so each request costs only the render.
use chimera::anatomy::human::{BodyMix, BodyName};
use chimera::phonetics::english::EnglishG2P;
use chimera::phonetics::planner::{PhraseInput, PlanOptions, plan_phrases};
use chimera::voice::human_voice::{HumanVoice, SourcePatch, VoiceTelemetry};
use serde::Deserialize;
use serde_json::{Value, json};
use std::io::{BufRead, Read, Write};
use std::time::Instant;

const FS: f64 = 48000.0;
const BLOCK: usize = 128;
/// audio blocks per motion snapshot: 12 x 128 samples = 31.25 snapshots a second
const MOTION_EVERY: usize = 12;

/// One telemetry snapshot as compact JSON: 4 decimals, every 4th scope point, no gesture labels.
fn snapshot(t: &VoiceTelemetry) -> Value {
    fn round(v: &mut Value) {
        match v {
            Value::Number(n) => *v = json!((n.as_f64().unwrap_or(0.0) * 1e4).round() / 1e4),
            Value::Array(a) => a.iter_mut().for_each(round),
            Value::Object(o) => o.values_mut().for_each(round),
            _ => {}
        }
    }
    let mut v = serde_json::to_value(t).unwrap_or(Value::Null);
    if let Value::Object(o) = &mut v {
        o.insert("active".into(), json!([]));
        for key in ["glottalArea", "glottalFlow"] {
            if let Some(Value::Array(a)) = o.get_mut(key) {
                *a = a.iter().step_by(4).cloned().collect();
            }
        }
    }
    round(&mut v);
    v
}

#[derive(Deserialize)]
struct Req {
    text: String,
    out: String,
    #[serde(default)]
    female: f64,
    #[serde(default)]
    child: f64,
    f0: Option<f64>,
    rate: Option<f64>,
    accent: Option<f64>,
    #[serde(default)]
    source: SourcePatch,
    motion: Option<String>,
}

fn say(g: &EnglishG2P, r: &Req) -> Result<f64, String> {
    let mix = BodyMix::new(r.female, r.child);
    let f0 = r.f0.unwrap_or_else(|| {
        mix.blend(|b| match b {
            BodyName::Female => 205.0,
            BodyName::Child => 250.0,
            BodyName::Male => 112.0,
        })
    });
    let mut voice = HumanVoice::new(FS, mix.body(), 2);
    voice.set_source(&SourcePatch { f0: Some(f0), ..r.source });
    let phrases: Vec<PhraseInput> = g
        .to_phrases(&r.text)
        .into_iter()
        .map(|p| PhraseInput { segments: p.segments, intonation: Some(p.intonation), pause: Some(p.pause) })
        .collect();
    let plan = plan_phrases(
        &phrases,
        &PlanOptions { body: mix, t0: 0.03, f0: Some(f0), rate: r.rate, accent: r.accent, ..Default::default() },
    );
    voice.schedule(&plan.gestures);
    let mut pcm = vec![0f32; (FS * (plan.end + 0.12)) as usize];
    let (mut tele, mut frames) = (VoiceTelemetry::default(), Vec::new());
    for (i, block) in pcm.chunks_mut(BLOCK).enumerate() {
        voice.render(block);
        if r.motion.is_some() && (i + 1) % MOTION_EVERY == 0 {
            voice.telemetry(&mut tele);
            frames.push(snapshot(&tele));
        }
    }
    if let Some(path) = &r.motion {
        let doc = json!({"fps": FS / (BLOCK * MOTION_EVERY) as f64,
                         "body": {"female": r.female, "child": r.child}, "frames": frames});
        std::fs::write(path, doc.to_string()).map_err(|e| format!("{path}: {e}"))?;
    }
    let bytes = pcm.len() as u32 * 2;
    let mut wav = Vec::with_capacity(44 + bytes as usize);
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&(36 + bytes).to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    for v in [16u32, 0x0001_0001, FS as u32, FS as u32 * 2, 0x0010_0002] {
        wav.extend_from_slice(&v.to_le_bytes()); // fmt size, PCM+mono, rate, byte rate, align+bits
    }
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&bytes.to_le_bytes());
    for s in &pcm {
        wav.extend_from_slice(&((s.clamp(-1.0, 1.0) * 32767.0) as i16).to_le_bytes());
    }
    std::fs::write(&r.out, wav).map_err(|e| format!("{}: {e}", r.out))?;
    Ok(pcm.len() as f64 / FS)
}

fn main() {
    let dict = std::env::args().nth(1).expect("usage: chimera-say <cmudict.txt.gz>");
    let gz = std::fs::read(&dict).unwrap_or_else(|e| panic!("{dict}: {e}"));
    let mut text = String::new();
    flate2::read::GzDecoder::new(&gz[..]).read_to_string(&mut text).expect("bad dictionary");
    let mut g = EnglishG2P::new();
    g.load_dict(&text);
    let mut out = std::io::stdout();
    writeln!(out, "{}", json!({"ok": true, "ready": true})).unwrap();
    out.flush().unwrap();
    for line in std::io::stdin().lock().lines() {
        let Ok(line) = line else { break };
        let t = Instant::now();
        let reply = match serde_json::from_str::<Req>(&line).map_err(|e| e.to_string()).and_then(|r| say(&g, &r)) {
            Ok(seconds) => json!({"ok": true, "seconds": seconds, "ms": t.elapsed().as_millis() as u64}),
            Err(error) => json!({"ok": false, "error": error}),
        };
        writeln!(out, "{reply}").unwrap();
        out.flush().unwrap();
    }
}
