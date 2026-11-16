// main.rs

use std::io::Write;
use std::path::PathBuf;
use std::process::ExitCode;

use simplechat_onenote_extractor::error::Error;
use simplechat_onenote_extractor::limits::{PARSER_REVISION, PROTOCOL_VERSION};
use simplechat_onenote_extractor::{extract_file_with_source_filename, runtime};

fn emit(response: runtime::Response) -> ExitCode {
    if std::io::stdout().lock().write_all(&response.bytes).is_err() {
        return ExitCode::from(2);
    }
    ExitCode::from(response.code)
}

fn main() -> ExitCode {
    std::panic::set_hook(Box::new(|_| {}));
    let _guard = match runtime::apply() {
        Ok(guard) => guard,
        Err(error) => return emit(runtime::Response::error(error)),
    };
    let mut args = std::env::args_os().skip(1);
    let Some(argument) = args.next() else {
        return emit(runtime::Response::error(Error::InvalidFile));
    };
    let source_filename = args.next();
    if args.next().is_some() || (argument == "--version" && source_filename.is_some()) {
        return emit(runtime::Response::error(Error::InvalidFile));
    }
    if argument == "--version" {
        return emit(runtime::Response {
            bytes: format!(
                "simplechat-onenote-extractor {} protocol={} parser={}\n",
                env!("CARGO_PKG_VERSION"),
                PROTOCOL_VERSION,
                PARSER_REVISION,
            )
            .into_bytes(),
            code: 0,
        });
    }
    let path = PathBuf::from(argument);
    emit(runtime::execute(|| {
        let source_filename = source_filename
            .as_deref()
            .map(|filename| filename.to_str().ok_or(Error::InvalidFile))
            .transpose()?;
        extract_file_with_source_filename(&path, source_filename)
    }))
}
