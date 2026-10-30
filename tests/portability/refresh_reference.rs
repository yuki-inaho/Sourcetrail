//! A value-level reference port for conformance, not a Rust source indexer.
//! No crates, filesystem paths, database, process execution, or FFI enter the policy.

use std::collections::BTreeSet;
use std::io::{self, BufRead, Write};

type Files = BTreeSet<u8>;

fn files(mask: u64) -> Files {
    (0..64).filter(|file| mask & (1_u64 << file) != 0).collect()
}

fn mask(files: &Files) -> u64 {
    files.iter().fold(0, |bits, file| bits | (1_u64 << file))
}

fn refresh(inputs: &[Files], omit_shared_protection: bool) -> [Files; 4] {
    let affected: Files = inputs[2].union(&inputs[3]).copied().collect();
    let retained: Files = inputs[0].difference(&affected).copied().collect();
    let protected: Files = retained.union(&inputs[4]).copied().collect();
    let extra: Files = if omit_shared_protection {
        inputs[5].clone()
    } else {
        inputs[5].difference(&protected).copied().collect()
    };
    let clear: Files = affected.union(&extra).copied().collect();
    let index: Files = inputs[0]
        .iter()
        .filter(|file| clear.contains(file) || !inputs[1].contains(file))
        .copied()
        .collect();
    [affected, retained, clear, index]
}

fn run() -> Result<(), String> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let omit_shared_protection = match arguments.as_slice() {
        [] => false,
        [flag] if flag == "--omit-shared-protection" => true,
        _ => return Err("unknown arguments".into()),
    };
    let mut count = 0;
    let mut output = io::BufWriter::new(io::stdout().lock());
    for (number, line) in io::stdin().lock().lines().enumerate() {
        let line = line.map_err(|error| error.to_string())?;
        if !line.is_ascii() {
            return Err(format!("line {}: input must be ASCII", number + 1));
        }
        let tokens: Vec<&str> = line.split_whitespace().collect();
        if tokens.len() != 6 {
            return Err(format!("line {}: expected exactly six masks", number + 1));
        }
        let mut inputs = Vec::with_capacity(6);
        for token in tokens {
            if token.is_empty() || !token.bytes().all(|byte| byte.is_ascii_digit()) {
                return Err(format!("line {}: expected an unsigned decimal mask", number + 1));
            }
            inputs.push(files(token.parse::<u64>().map_err(|error| error.to_string())?));
        }
        let result = refresh(&inputs, omit_shared_protection);
        writeln!(output, "{} {} {} {}", mask(&result[0]), mask(&result[1]), mask(&result[2]), mask(&result[3]))
            .map_err(|error| error.to_string())?;
        count += 1;
    }
    if count == 0 {
        return Err("input must contain at least one complete case".into());
    }
    output.flush().map_err(|error| error.to_string())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}
