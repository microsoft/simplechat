// extract.rs

use std::io::{self, Write};

use bytes::Bytes;
use onenote_parser::Parser;
use onenote_parser::section::{Section, SectionEntry};
use serde::Serialize;
use typed_path::{PathType, TypedPath};

use crate::error::{Error, Result, parser_error};
use crate::limits::{
    MAX_COMPONENT_CHARS, MAX_DEPTH, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, MAX_PAGES, MAX_TEXT_BYTES,
    MAX_TITLE_CHARS, PARSER_REVISION, PROTOCOL_VERSION,
};
use crate::text::{self, ExcludedContent, Text};
use crate::vfs::{MemoryFs, Store};

#[derive(Debug, Serialize)]
pub struct Page {
    pub section_path: Vec<String>,
    pub id: String,
    pub title: String,
    pub level: u32,
    pub text: String,
}

#[derive(Debug, Serialize)]
pub struct Document {
    pub protocol_version: u32,
    pub parser_revision: &'static str,
    pub sections: usize,
    pub source_pages: usize,
    pub pages: Vec<Page>,
    pub excluded_content: ExcludedContent,
}

impl Document {
    fn new(attachments: usize) -> Self {
        Self {
            protocol_version: PROTOCOL_VERSION,
            parser_revision: PARSER_REVISION,
            sections: 0,
            source_pages: 0,
            pages: Vec::new(),
            excluded_content: ExcludedContent {
                attachments,
                ..Default::default()
            },
        }
    }

    fn add_section(
        &mut self,
        section: &Section,
        path: Vec<String>,
        used_text: &mut usize,
    ) -> Result<()> {
        if path.is_empty() || path.len() > MAX_DEPTH {
            return Err(Error::LimitExceeded);
        }
        if path
            .iter()
            .any(|component| component.chars().count() > MAX_COMPONENT_CHARS)
        {
            return Err(Error::LimitExceeded);
        }
        if section
            .report()
            .warnings()
            .iter()
            .any(|warning| !text::excluded_warning(warning.message()))
        {
            return Err(Error::IncompleteNotebook);
        }
        self.sections += 1;
        for page in section
            .page_series()
            .iter()
            .flat_map(|series| series.pages())
        {
            if self.pages.len() >= MAX_PAGES {
                return Err(Error::LimitExceeded);
            }
            let level = u32::try_from(page.level()).map_err(|_| Error::InvalidFile)?;
            if level == 0 {
                return Err(Error::InvalidFile);
            }
            if level as usize > MAX_DEPTH {
                return Err(Error::LimitExceeded);
            }
            let mut title = Text::new((MAX_TITLE_CHARS * 4).min(MAX_TEXT_BYTES - *used_text));
            if let Some(outline) = page.title().and_then(|title| title.contents().first()) {
                text::outline(outline.items(), &mut title, &mut self.excluded_content, 1)?;
            }
            let title = title.finish();
            if title.chars().count() > MAX_TITLE_CHARS {
                return Err(Error::LimitExceeded);
            }
            *used_text += title.len();
            let mut body = Text::new(MAX_TEXT_BYTES - *used_text);
            text::page(page.contents(), &mut body, &mut self.excluded_content)?;
            let mut body = body.finish();
            if body.trim().is_empty() && !title.trim().is_empty() {
                if title.len() > MAX_TEXT_BYTES - *used_text {
                    return Err(Error::LimitExceeded);
                }
                body.clone_from(&title);
            }
            *used_text += body.len();
            if body.trim().is_empty() {
                self.excluded_content.empty_pages += 1;
            }
            self.pages.push(Page {
                section_path: path.clone(),
                id: page.link_target_id().to_owned(),
                title,
                level,
                text: body,
            });
        }
        Ok(())
    }

    fn finish(mut self) -> Result<Self> {
        self.source_pages = self.pages.len();
        if self.pages.iter().all(|page| page.text.trim().is_empty()) {
            return Err(Error::NoText);
        }
        Ok(self)
    }
}

fn sections<'a>(
    entries: &'a [SectionEntry],
    output: &mut Vec<&'a Section>,
    group_count: &mut usize,
    depth: usize,
) -> Result<()> {
    if depth > MAX_DEPTH {
        return Err(Error::LimitExceeded);
    }
    for entry in entries {
        match entry {
            SectionEntry::Section(section) => output.push(section),
            SectionEntry::SectionGroup(group) => {
                *group_count += 1;
                sections(group.entries(), output, group_count, depth + 1)?;
            }
        }
    }
    Ok(())
}

pub fn section(data: Bytes) -> Result<Document> {
    section_with_source_filename(data, None)
}

pub fn section_with_source_filename(
    data: Bytes,
    source_filename: Option<&str>,
) -> Result<Document> {
    if data.len() > MAX_INPUT_BYTES {
        return Err(Error::LimitExceeded);
    }
    crate::signature::validate(&data, false)?;
    let source_filename = source_filename
        .map(|filename| crate::source_name::normalize(filename, false))
        .transpose()?;
    let store = Store::single(data.clone());
    let parser = Parser::new_with_fs(MemoryFs(&store));
    let section = match source_filename.as_deref() {
        // The pinned buffer API uses this argument only as a metadata fallback
        // and diagnostic label. It never opens it, and a stored name wins.
        Some(filename) => {
            parser.parse_section_buffer(&data, TypedPath::new(filename, PathType::Windows))
        }
        None => parser.parse_section(Store::virtual_path("section.one").to_path()),
    }
    .map_err(|error| parser_error(&error))?;
    if source_filename.is_none() {
        store.verify_coverage(1, 0)?;
    }
    let mut result = Document::new(0);
    let mut used = 0;
    result.add_section(&section, vec![section.display_name().to_owned()], &mut used)?;
    result.finish()
}

pub fn package(data: &[u8]) -> Result<Document> {
    let archive = crate::package::extract(data)?;
    let attachments = archive.attachments;
    let store = Store::new(archive);
    let parser = Parser::new_with_fs(MemoryFs(&store));
    let notebook = parser
        .parse_notebook(Store::virtual_path(&store.root_toc).to_path())
        .map_err(|error| store.failure().unwrap_or_else(|| parser_error(&error)))?;
    if let Some(error) = store.failure() {
        return Err(error);
    }
    if !notebook.report().warnings().is_empty() {
        return Err(Error::IncompleteNotebook);
    }
    let mut parsed_sections = Vec::new();
    let mut group_count = 0;
    sections(
        notebook.entries(),
        &mut parsed_sections,
        &mut group_count,
        1,
    )?;
    let opened = store.verify_coverage(parsed_sections.len(), group_count)?;
    let mut result = Document::new(attachments);
    let mut used = 0;
    for (section, key) in parsed_sections.into_iter().zip(opened) {
        result.add_section(section, store.section_path(&key)?, &mut used)?;
    }
    result.finish()
}

struct BoundedOutput {
    bytes: Vec<u8>,
    limit: usize,
}

impl Write for BoundedOutput {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > self.limit.saturating_sub(self.bytes.len()) {
            return Err(io::Error::from(io::ErrorKind::FileTooLarge));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn serialize_with_limit(document: &Document, limit: usize) -> Result<Vec<u8>> {
    let mut writer = BoundedOutput {
        bytes: Vec::new(),
        limit,
    };
    serde_json::to_writer(&mut writer, document).map_err(|_| Error::LimitExceeded)?;
    Ok(writer.bytes)
}

pub fn serialize(document: &Document) -> Result<Vec<u8>> {
    serialize_with_limit(document, MAX_OUTPUT_BYTES)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fails_atomically_when_json_escaping_crosses_output_limit() {
        let mut document = Document::new(0);
        document.pages.push(Page {
            section_path: vec!["section".to_owned()],
            id: "id".to_owned(),
            title: String::new(),
            level: 1,
            text: "\"".repeat(100),
        });
        let result = serialize_with_limit(&document, 100);
        assert_eq!(result, Err(Error::LimitExceeded));
    }

    #[test]
    fn source_page_count_retains_blank_pages_and_no_text_is_not_success() {
        let mut document = Document::new(0);
        for text in ["", "visible", ""] {
            document.pages.push(Page {
                section_path: vec!["section".to_owned()],
                id: "id".to_owned(),
                title: String::new(),
                level: 1,
                text: text.to_owned(),
            });
        }
        let document = document.finish().unwrap();
        assert_eq!(document.source_pages, 3);
        assert_eq!(document.pages.len(), 3);
        let empty = Document::new(0).finish();
        assert!(matches!(empty, Err(Error::NoText)));
    }

    #[test]
    fn every_failure_has_only_the_stable_protocol_and_code() {
        for error in [
            Error::InvalidFile,
            Error::UnsupportedFile,
            Error::EncryptedFile,
            Error::UnsafePackage,
            Error::LimitExceeded,
            Error::IncompleteNotebook,
            Error::NoText,
            Error::ExtractionFailed,
        ] {
            let value: serde_json::Value = serde_json::from_slice(&error.response()).unwrap();
            assert_eq!(value.as_object().unwrap().len(), 2);
            assert_eq!(value["protocol_version"], PROTOCOL_VERSION);
            assert_eq!(value["error"].as_object().unwrap().len(), 1);
            assert!(value.get("pages").is_none());
        }
    }

    #[test]
    fn rejects_page_and_total_text_budgets_before_adding_another_page() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("fixtures")
            .join("New Section 1.one");
        let bytes = std::fs::read(path).unwrap();
        let store = Store::single(Bytes::from(bytes));
        let section = Parser::new_with_fs(MemoryFs(&store))
            .parse_section(Store::virtual_path("section.one").to_path())
            .unwrap();
        let mut full = Document::new(0);
        for _ in 0..MAX_PAGES {
            full.pages.push(Page {
                section_path: vec!["section".to_owned()],
                id: "id".to_owned(),
                title: String::new(),
                level: 1,
                text: String::new(),
            });
        }
        let too_many = full.add_section(&section, vec!["section".to_owned()], &mut 0);
        let mut used = MAX_TEXT_BYTES;
        let mut no_space = Document::new(0);
        let too_much = no_space.add_section(&section, vec!["section".to_owned()], &mut used);
        assert_eq!(too_many, Err(Error::LimitExceeded));
        assert_eq!(too_much, Err(Error::LimitExceeded));
        assert_eq!(full.pages.len(), MAX_PAGES);
        assert!(no_space.pages.is_empty());
    }
}
