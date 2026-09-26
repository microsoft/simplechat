// source_name.rs

use crate::error::{Error, Result};
use crate::limits::MAX_COMPONENT_CHARS;

pub(crate) fn normalize(filename: &str, package: bool) -> Result<String> {
    if filename.chars().count() > MAX_COMPONENT_CHARS {
        return Err(Error::LimitExceeded);
    }
    if filename.is_empty()
        || filename
            .chars()
            .any(|ch| ch.is_control() || matches!(ch, '/' | '\\' | ':'))
    {
        return Err(Error::InvalidFile);
    }
    let extension = if package { ".onepkg" } else { ".one" };
    let start = filename
        .len()
        .checked_sub(extension.len())
        .ok_or(Error::InvalidFile)?;
    let suffix = filename.get(start..).ok_or(Error::InvalidFile)?;
    if !suffix.eq_ignore_ascii_case(extension) || filename[..start].trim().is_empty() {
        return Err(Error::InvalidFile);
    }
    Ok(format!("{}{extension}", &filename[..start]))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_only_the_display_filename_extension() {
        let filename = normalize("Café 😀.ONE", false).unwrap();
        assert_eq!(filename, "Café 😀.one");
        let package = normalize("Book.ONEPKG", true).unwrap();
        assert_eq!(package, "Book.onepkg");
    }

    #[test]
    fn rejects_paths_control_characters_empty_stems_and_wrong_suffixes() {
        for filename in [
            "",
            ".one",
            "  .one",
            "../label.one",
            "group\\label.one",
            "/label.one",
            "C:label.one",
            "\\\\host\\label.one",
            "label\0.one",
            "label\n.one",
            "label.onepkg",
            "label.txt",
            "label.one ",
        ] {
            let result = normalize(filename, false);
            assert_eq!(result, Err(Error::InvalidFile));
        }
    }

    #[test]
    fn bounds_unicode_scalars_not_utf8_bytes() {
        let maximum = format!("{}.one", "😀".repeat(MAX_COMPONENT_CHARS - 4));
        let accepted = normalize(&maximum, false);
        let rejected = normalize(&format!("x{maximum}"), false);
        assert!(accepted.is_ok());
        assert_eq!(rejected, Err(Error::LimitExceeded));
    }
}
