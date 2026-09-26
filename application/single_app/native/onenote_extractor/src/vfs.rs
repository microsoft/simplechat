// vfs.rs

use std::collections::{BTreeMap, BTreeSet};
use std::io;
use std::sync::{Arc, Mutex};

use bytes::Bytes;
use onenote_parser::FileSystem;
use onenote_parser::fs::{FileSource, file_source::BytesSource};
use typed_path::{PathType, TypedPath, TypedPathBuf};

use crate::error::{Error, Result};
use crate::package::Archive;
use crate::paths::{MemberPath, case_key, inside};

#[derive(Default)]
struct Access {
    failure: Option<Error>,
    sections: Vec<String>,
    tocs: BTreeSet<String>,
}

pub(crate) struct Store {
    files: BTreeMap<String, (MemberPath, Bytes)>,
    directories: BTreeMap<String, String>,
    root_directory: String,
    pub root_toc: String,
    access: Mutex<Access>,
}

impl Store {
    pub fn new(archive: Archive) -> Self {
        let mut directories = BTreeMap::from([(String::new(), String::new())]);
        let mut files = BTreeMap::new();
        for (path, bytes) in archive.files {
            for (index, _) in path.name.match_indices('\\') {
                let directory = &path.name[..index];
                directories
                    .entry(case_key(directory))
                    .or_insert_with(|| directory.to_owned());
            }
            files.insert(path.key.clone(), (path, bytes));
        }
        Self {
            files,
            directories,
            root_directory: archive.root_directory,
            root_toc: archive.root_toc,
            access: Mutex::new(Access::default()),
        }
    }

    pub fn single(bytes: Bytes) -> Self {
        let path = MemberPath::parse("section.one").expect("constant path is safe");
        Self::new(Archive {
            files: vec![(path, bytes)],
            root_toc: String::new(),
            root_directory: String::new(),
            attachments: 0,
        })
    }

    pub fn virtual_path(name: &str) -> TypedPathBuf {
        let path = if name.is_empty() {
            "archive".to_owned()
        } else {
            format!("archive\\{name}")
        };
        TypedPath::new(&path, PathType::Windows).to_path_buf()
    }

    fn denied<T>(&self, code: Error) -> io::Result<T> {
        let mut access = self.access.lock().map_err(|_| io::ErrorKind::Other)?;
        access.failure.get_or_insert(code);
        Err(io::Error::from(io::ErrorKind::PermissionDenied))
    }

    fn key(&self, path: TypedPath<'_>) -> io::Result<String> {
        let Ok(raw) = std::str::from_utf8(path.as_bytes()) else {
            return self.denied(Error::UnsafePackage);
        };
        let raw = raw.replace('/', "\\");
        let key = if raw == "archive" {
            String::new()
        } else if let Some(relative) = raw.strip_prefix("archive\\") {
            match MemberPath::parse(relative) {
                Ok(path) => path.key,
                Err(error) => return self.denied(error),
            }
        } else {
            return self.denied(Error::UnsafePackage);
        };
        if key != self.root_directory && !inside(&key, &self.root_directory) {
            return self.denied(Error::UnsafePackage);
        }
        Ok(key)
    }

    fn is_recycle_bin(key: &str) -> bool {
        key.split('\\').any(|part| part == "ONENOTE_RECYCLEBIN")
    }

    pub fn failure(&self) -> Option<Error> {
        self.access
            .lock()
            .map_or(Some(Error::ExtractionFailed), |access| access.failure)
    }

    pub fn verify_coverage(
        &self,
        returned_sections: usize,
        returned_groups: usize,
    ) -> Result<Vec<String>> {
        let access = self.access.lock().map_err(|_| Error::ExtractionFailed)?;
        if let Some(error) = access.failure {
            return Err(error);
        }
        let expected_sections: BTreeSet<_> = self
            .files
            .iter()
            .filter(|(_, (path, _))| path.is_section())
            .map(|(key, _)| key.clone())
            .collect();
        let expected_tocs: BTreeSet<_> = self
            .files
            .iter()
            .filter(|(_, (path, _))| path.is_toc())
            .map(|(key, _)| key.clone())
            .collect();
        let opened_sections: BTreeSet<_> = access.sections.iter().cloned().collect();
        if expected_sections != opened_sections
            || access.sections.len() != returned_sections
            || expected_tocs != access.tocs
            || expected_tocs.len() != returned_groups + usize::from(!self.root_toc.is_empty())
        {
            return Err(Error::IncompleteNotebook);
        }
        Ok(access.sections.clone())
    }

    pub fn section_path(&self, key: &str) -> Result<Vec<String>> {
        let (path, _) = self.files.get(key).ok_or(Error::IncompleteNotebook)?;
        let prefix_count = if self.root_directory.is_empty() {
            0
        } else {
            self.root_directory.split('\\').count()
        };
        let mut components = Vec::new();
        for index in prefix_count..path.components.len() - 1 {
            let key = case_key(&path.components[..=index].join("\\"));
            let directory = self
                .directories
                .get(&key)
                .ok_or(Error::IncompleteNotebook)?;
            let name = directory
                .rsplit('\\')
                .next()
                .ok_or(Error::IncompleteNotebook)?;
            components.push(name.to_owned());
        }
        let name = path.components.last().ok_or(Error::IncompleteNotebook)?;
        let length = name.len().checked_sub(4).ok_or(Error::IncompleteNotebook)?;
        if length == 0 {
            return Err(Error::UnsafePackage);
        }
        components.push(name[..length].to_owned());
        Ok(components)
    }
}

#[derive(Clone, Copy)]
pub(crate) struct MemoryFs<'a>(pub &'a Store);

impl FileSystem for MemoryFs<'_> {
    fn is_directory(&self, path: TypedPath<'_>) -> io::Result<bool> {
        let key = self.0.key(path)?;
        if Store::is_recycle_bin(&key) {
            return Ok(false);
        }
        if self.0.directories.contains_key(&key) {
            return Ok(true);
        }
        if self.0.files.contains_key(&key) {
            return Ok(false);
        }
        self.0.denied(Error::IncompleteNotebook)
    }

    fn read_dir(&self, path: TypedPath<'_>) -> io::Result<Vec<TypedPathBuf>> {
        let key = self.0.key(path)?;
        if !self.0.directories.contains_key(&key) || Store::is_recycle_bin(&key) {
            return self.0.denied(Error::IncompleteNotebook);
        }
        let parent_key = |key: &str| {
            key.rsplit_once('\\')
                .map_or("", |(parent, _)| parent)
                .to_owned()
        };
        let mut result = Vec::new();
        for (candidate, name) in &self.0.directories {
            if !candidate.is_empty()
                && parent_key(candidate) == key
                && !Store::is_recycle_bin(candidate)
            {
                result.push(Store::virtual_path(name));
            }
        }
        for (candidate, (member, _)) in &self.0.files {
            if parent_key(candidate) == key {
                let name = if member.is_toc() {
                    // The upstream group enumerator compares this extension
                    // case-sensitively; lookup remains case-insensitive.
                    format!("{}.onetoc2", &member.name[..member.name.len() - 8])
                } else {
                    member.name.clone()
                };
                result.push(Store::virtual_path(&name));
            }
        }
        Ok(result)
    }

    fn read_file(&self, path: TypedPath<'_>) -> io::Result<Vec<u8>> {
        let source = self.open_file(path)?;
        Ok(source.as_bytes().ok_or(io::ErrorKind::Other)?.to_vec())
    }

    fn open_file(&self, path: TypedPath<'_>) -> io::Result<Arc<dyn FileSource>> {
        let key = self.0.key(path)?;
        let Some((member, bytes)) = self.0.files.get(&key) else {
            return self.0.denied(Error::IncompleteNotebook);
        };
        if !member.is_payload() {
            return self.0.denied(Error::UnsafePackage);
        }
        {
            let mut access = self.0.access.lock().map_err(|_| io::ErrorKind::Other)?;
            let duplicate = if member.is_toc() {
                !access.tocs.insert(key.clone())
            } else {
                let duplicate = access.sections.contains(&key);
                access.sections.push(key);
                duplicate
            };
            if duplicate {
                access.failure.get_or_insert(Error::UnsafePackage);
                return Err(io::Error::from(io::ErrorKind::PermissionDenied));
            }
        }
        Ok(Arc::new(BytesSource::new(bytes.clone())))
    }

    fn canonicalize(&self, path: TypedPath<'_>) -> io::Result<TypedPathBuf> {
        let key = self.0.key(path)?;
        if self.0.files.contains_key(&key) || self.0.directories.contains_key(&key) {
            Ok(Store::virtual_path(&key))
        } else {
            self.0.denied(Error::IncompleteNotebook)
        }
    }

    fn exists(&self, path: TypedPath<'_>) -> io::Result<bool> {
        let key = self.0.key(path)?;
        if Store::is_recycle_bin(&key) {
            return Ok(false);
        }
        if self.0.files.contains_key(&key) || self.0.directories.contains_key(&key) {
            Ok(true)
        } else {
            // parse_notebook swallows this error with unwrap_or(false).
            // Keep a durable failure for the boundary to inspect afterwards.
            self.0.denied(Error::IncompleteNotebook)
        }
    }

    fn write_file(&self, _path: TypedPath<'_>, _data: &[u8]) -> io::Result<()> {
        self.0.denied(Error::UnsafePackage)
    }

    fn stream_to_file(&self, _path: TypedPath<'_>, _reader: &mut dyn io::Read) -> io::Result<()> {
        self.0.denied(Error::UnsafePackage)
    }

    fn make_dir(&self, _path: TypedPath<'_>) -> io::Result<()> {
        self.0.denied(Error::UnsafePackage)
    }

    fn is_windows(&self) -> bool {
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn store(names: &[&str]) -> Store {
        Store::new(Archive {
            files: names
                .iter()
                .map(|name| {
                    (
                        MemberPath::parse(name).unwrap(),
                        Bytes::from_static(b"fixture"),
                    )
                })
                .collect(),
            root_toc: "Open.onetoc2".to_owned(),
            root_directory: String::new(),
            attachments: 0,
        })
    }

    #[test]
    fn missing_exists_calls_are_not_silently_ignored() {
        let store = store(&["Open.onetoc2"]);
        let fs = MemoryFs(&store);
        let missing = fs
            .exists(Store::virtual_path("Missing.one").to_path())
            .unwrap_or(false);
        let coverage = store.verify_coverage(0, 0);
        assert!(!missing);
        assert_eq!(coverage, Err(Error::IncompleteNotebook));
    }

    #[test]
    fn rejects_external_access_and_mutations() {
        for path in [
            r"C:\secret.one",
            r"\\server\secret.one",
            r"archive\..\secret.one",
        ] {
            let store = store(&["Open.onetoc2"]);
            let result = MemoryFs(&store).open_file(TypedPath::new(path, PathType::Windows));
            assert!(result.is_err());
            assert_eq!(store.failure(), Some(Error::UnsafePackage));
        }
        let store = store(&["Open.onetoc2"]);
        let result = MemoryFs(&store).write_file(Store::virtual_path("x").to_path(), b"x");
        assert!(result.is_err());
        assert_eq!(store.failure(), Some(Error::UnsafePackage));
    }

    #[test]
    fn repeated_toc_access_breaks_recursive_loops() {
        let store = store(&["Open.onetoc2"]);
        let fs = MemoryFs(&store);
        let first = fs.open_file(Store::virtual_path("Open.onetoc2").to_path());
        let second = fs.open_file(Store::virtual_path("OPEN.ONETOC2").to_path());
        assert!(first.is_ok());
        assert!(second.is_err());
        assert_eq!(store.failure(), Some(Error::UnsafePackage));
    }

    #[test]
    fn inventory_catches_lost_nested_warnings_and_unvisited_empty_groups() {
        let store = store(&["Open.onetoc2", "G\\Open.onetoc2", "G\\A.one", "G\\B.one"]);
        let fs = MemoryFs(&store);
        for name in ["Open.onetoc2", "G\\Open.onetoc2", "G\\A.one", "G\\B.one"] {
            let opened = fs.open_file(Store::virtual_path(name).to_path());
            assert!(opened.is_ok());
        }
        let lost_section = store.verify_coverage(1, 1);
        let complete = store.verify_coverage(2, 1);
        assert_eq!(lost_section, Err(Error::IncompleteNotebook));
        assert!(complete.is_ok());

        let empty_group = super::tests::store(&["Open.onetoc2", "G\\Open.onetoc2"]);
        let opened =
            MemoryFs(&empty_group).open_file(Store::virtual_path("Open.onetoc2").to_path());
        let unvisited = empty_group.verify_coverage(0, 0);
        assert!(opened.is_ok());
        assert_eq!(unvisited, Err(Error::IncompleteNotebook));
    }

    #[test]
    fn well_defined_recycle_bin_is_optional_and_not_opened() {
        let store = store(&["Open.onetoc2"]);
        let exists = MemoryFs(&store)
            .exists(Store::virtual_path("OneNote_RecycleBin").to_path())
            .unwrap();
        assert!(!exists);
        assert_eq!(store.failure(), None);
    }

    #[test]
    fn safe_actual_case_is_retained_in_section_hierarchy() {
        let store = store(&["Open.onetoc2", "Group\\Section.ONE"]);
        let path = store.section_path("GROUP\\SECTION.ONE").unwrap();
        assert_eq!(path, ["Group", "Section"]);
    }

    #[test]
    fn directory_case_aliases_do_not_split_one_group_into_two() {
        let store = store(&["Open.onetoc2", "Group\\A.one", "GROUP\\Child\\B.one"]);
        let a = store.section_path("GROUP\\A.ONE").unwrap();
        let b = store.section_path("GROUP\\CHILD\\B.ONE").unwrap();
        assert_eq!(a[0], b[0]);
        assert_eq!(b, ["Group", "Child", "B"]);
    }

    #[test]
    fn opened_but_failed_empty_nested_toc_cannot_evade_section_coverage() {
        let store = store(&[
            "Open.onetoc2",
            "G\\Open.onetoc2",
            "G\\Inner\\Open.onetoc2",
            "Live.one",
        ]);
        let fs = MemoryFs(&store);
        for name in [
            "Open.onetoc2",
            "G\\Open.onetoc2",
            "G\\Inner\\Open.onetoc2",
            "Live.one",
        ] {
            let opened = fs.open_file(Store::virtual_path(name).to_path());
            assert!(opened.is_ok());
        }
        let incomplete = store.verify_coverage(1, 1);
        let complete = store.verify_coverage(1, 2);
        assert_eq!(incomplete, Err(Error::IncompleteNotebook));
        assert!(complete.is_ok());
    }
}
