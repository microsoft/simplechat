// lib.rs

pub mod error;
pub mod extract;
pub mod limits;
mod package;
mod paths;
pub mod runtime;
mod signature;
mod source_name;
mod text;
mod vfs;

use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;

use bytes::Bytes;

use error::{Error, Result};
use limits::{IO_CHUNK_BYTES, MAX_INPUT_BYTES};

pub fn extract_file(path: &Path) -> Result<Vec<u8>> {
    extract_file_with_source_filename(path, None)
}

pub fn extract_file_with_source_filename(
    path: &Path,
    source_filename: Option<&str>,
) -> Result<Vec<u8>> {
    if !path.is_absolute() {
        return Err(Error::InvalidFile);
    }
    #[cfg(windows)]
    validate_windows_input(path)?;
    let extension = path
        .extension()
        .and_then(|extension| extension.to_str())
        .ok_or(Error::UnsupportedFile)?;
    let package = if extension.eq_ignore_ascii_case("onepkg") {
        true
    } else if extension.eq_ignore_ascii_case("one") {
        false
    } else {
        return Err(Error::UnsupportedFile);
    };
    if let Some(filename) = source_filename {
        source_name::normalize(filename, package)?;
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.custom_flags(windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT);
    }
    let mut file = options.open(path).map_err(|_| Error::InvalidFile)?;
    let metadata = file.metadata().map_err(|_| Error::InvalidFile)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(Error::InvalidFile);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes()
            & windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT
            != 0
        {
            return Err(Error::InvalidFile);
        }
    }
    if metadata.len() > MAX_INPUT_BYTES as u64 {
        return Err(Error::LimitExceeded);
    }
    let mut bytes = Vec::new();
    bytes
        .try_reserve_exact(metadata.len() as usize)
        .map_err(|_| Error::LimitExceeded)?;
    let mut chunk = [0; IO_CHUNK_BYTES];
    loop {
        let size = file.read(&mut chunk).map_err(|_| Error::InvalidFile)?;
        if size == 0 {
            break;
        }
        if size > MAX_INPUT_BYTES - bytes.len() {
            return Err(Error::LimitExceeded);
        }
        bytes.extend_from_slice(&chunk[..size]);
    }
    let document = if package {
        extract::package(&bytes)?
    } else {
        extract::section_with_source_filename(Bytes::from(bytes), source_filename)?
    };
    extract::serialize(&document)
}

#[cfg(windows)]
fn validate_windows_input(path: &Path) -> Result<()> {
    use std::path::{Component, Prefix};
    let mut components = path.components();
    match components.next() {
        Some(Component::Prefix(prefix))
            if matches!(prefix.kind(), Prefix::Disk(_) | Prefix::VerbatimDisk(_)) => {}
        _ => return Err(Error::InvalidFile),
    }
    for component in components {
        match component {
            Component::RootDir => {}
            Component::Normal(name) => {
                let name = name.to_str().ok_or(Error::InvalidFile)?;
                paths::MemberPath::parse(name).map_err(|_| Error::InvalidFile)?;
            }
            _ => return Err(Error::InvalidFile),
        }
    }
    Ok(())
}

#[cfg(all(test, windows))]
mod windows_tests {
    use super::*;

    #[test]
    fn input_paths_cannot_open_unc_or_device_names() {
        for path in [
            r"\\server\share\section.one",
            r"\\?\UNC\server\share\section.one",
            r"\\.\pipe\section.one",
            r"C:\NUL.one",
        ] {
            let result = validate_windows_input(Path::new(path));
            assert_eq!(result, Err(Error::InvalidFile));
        }
        let local = validate_windows_input(Path::new(r"C:\notes\section.one"));
        assert_eq!(local, Ok(()));
    }
}
