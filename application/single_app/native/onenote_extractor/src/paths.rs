// paths.rs

use crate::error::{Error, Result};
use crate::limits::{MAX_COMPONENT_CHARS, MAX_DEPTH};

#[derive(Clone, Debug)]
pub(crate) struct MemberPath {
    pub name: String,
    pub key: String,
    pub components: Vec<String>,
    pub recycle_bin: bool,
}

pub(crate) fn case_key(value: &str) -> String {
    value.to_uppercase()
}

impl MemberPath {
    pub fn parse(name: &str) -> Result<Self> {
        if name.is_empty()
            || name.starts_with(['/', '\\'])
            || name
                .chars()
                .any(|ch| ch.is_control() || matches!(ch, ':' | '<' | '>' | '"' | '|' | '?' | '*'))
        {
            return Err(Error::UnsafePackage);
        }
        let mut components = Vec::new();
        for component in name.split(['/', '\\']) {
            if component.is_empty()
                || matches!(component, "." | "..")
                || component.ends_with(['.', ' '])
            {
                return Err(Error::UnsafePackage);
            }
            if component.chars().count() > MAX_COMPONENT_CHARS || components.len() >= MAX_DEPTH {
                return Err(Error::LimitExceeded);
            }
            let base = component.split('.').next().unwrap_or_default();
            let reserved = case_key(base);
            if matches!(reserved.as_str(), "CON" | "PRN" | "AUX" | "NUL")
                || (reserved.len() == 4
                    && (reserved.starts_with("COM") || reserved.starts_with("LPT"))
                    && reserved.as_bytes()[3].is_ascii_digit())
            {
                return Err(Error::UnsafePackage);
            }
            components.push(component.to_owned());
        }
        let name = components.join("\\");
        let key = case_key(&name);
        let recycle_bin = components[..components.len() - 1]
            .iter()
            .any(|part| part.eq_ignore_ascii_case("OneNote_RecycleBin"));
        Ok(Self {
            name,
            key,
            components,
            recycle_bin,
        })
    }

    pub fn is_section(&self) -> bool {
        self.key.ends_with(".ONE")
    }

    pub fn is_toc(&self) -> bool {
        self.key.ends_with(".ONETOC2")
    }

    pub fn is_payload(&self) -> bool {
        !self.recycle_bin && (self.is_section() || self.is_toc())
    }

    pub fn parent_key(&self) -> &str {
        self.key.rsplit_once('\\').map_or("", |(parent, _)| parent)
    }
}

pub(crate) fn inside(path: &str, directory: &str) -> bool {
    directory.is_empty()
        || path
            .strip_prefix(directory)
            .is_some_and(|suffix| suffix.starts_with('\\'))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_unsafe_member_paths_without_normalizing_them() {
        for name in [
            "../a.one",
            "a\\..\\b.one",
            "/a.one",
            "\\a.one",
            "C:\\a.one",
            "C:a.one",
            "\\\\server\\share\\a.one",
            "a//b.one",
            "a/./b.one",
            "a/\0b.one",
            "a/\u{0085}b.one",
            "a.\\b.one",
            "a \\b.one",
            "a.one:stream",
            "https://example/a.one",
            "NUL.one",
            "COM1.one",
        ] {
            let result = MemberPath::parse(name);
            assert!(matches!(result, Err(Error::UnsafePackage)), "{name:?}");
        }
    }

    #[test]
    fn preserves_names_and_matches_windows_case() {
        let path = MemberPath::parse("Grüppe/Notes.ONE").unwrap();
        assert_eq!(path.name, "Grüppe\\Notes.ONE");
        assert_eq!(path.key, "GRÜPPE\\NOTES.ONE");
        assert!(path.is_section());
        assert_eq!(case_key("Σ"), case_key("ς"));
    }

    #[test]
    fn bounds_components_and_depth() {
        let long = format!("{}.one", "x".repeat(MAX_COMPONENT_CHARS));
        let deep = format!("{}a.one", "g\\".repeat(MAX_DEPTH));
        let long_result = MemberPath::parse(&long);
        let deep_result = MemberPath::parse(&deep);
        assert!(matches!(long_result, Err(Error::LimitExceeded)));
        assert!(matches!(deep_result, Err(Error::LimitExceeded)));
    }

    #[test]
    fn only_exact_recycle_bin_directories_are_excluded() {
        let deleted = MemberPath::parse("root/onenote_recyclebin/old.one").unwrap();
        let live = MemberPath::parse("root/OneNote_RecycleBin_notes/live.one").unwrap();
        let leaf = MemberPath::parse("root/OneNote_RecycleBin.one").unwrap();
        assert!(deleted.recycle_bin);
        assert!(!live.recycle_bin);
        assert!(!leaf.recycle_bin);
    }
}
