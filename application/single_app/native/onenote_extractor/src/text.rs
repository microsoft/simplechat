// text.rs

use onenote_parser::contents::{
    Content, EmbeddedObject, MathObjectType, OutlineElement, OutlineItem, RichText,
};
use onenote_parser::page::PageContent;
use serde::Serialize;

use crate::error::{Error, Result};
use crate::limits::MAX_DEPTH;

#[derive(Debug, Default, Serialize)]
pub struct ExcludedContent {
    pub images: usize,
    pub ink: usize,
    pub attachments: usize,
    pub empty_pages: usize,
}

pub(crate) struct Text {
    value: String,
    limit: usize,
}

impl Text {
    pub fn new(limit: usize) -> Self {
        Self {
            value: String::new(),
            limit,
        }
    }

    pub fn push(&mut self, value: &str) -> Result<()> {
        if value.len() > self.limit.saturating_sub(self.value.len()) {
            return Err(Error::LimitExceeded);
        }
        self.value.push_str(value);
        Ok(())
    }

    fn character(&mut self, ch: char) -> Result<()> {
        self.push(ch.encode_utf8(&mut [0; 4]))
    }

    fn remaining(&self) -> usize {
        self.limit.saturating_sub(self.value.len())
    }

    pub fn finish(mut self) -> String {
        let length = self.value.trim_end_matches(['\n', '\r', ' ']).len();
        self.value.truncate(length);
        self.value
    }
}

fn depth(value: usize) -> Result<()> {
    if value > MAX_DEPTH {
        Err(Error::LimitExceeded)
    } else {
        Ok(())
    }
}

// Offsets are UTF-16 code units, not UTF-8 bytes or Unicode scalar indices.
// Reject malformed run metadata rather than guessing which text was visible.
fn visible_runs(
    text: &str,
    indices: &[u32],
    hidden: &[bool],
    base_hidden: bool,
    output: &mut Text,
) -> Result<()> {
    if text.is_empty() {
        return Ok(());
    }
    let total = text.encode_utf16().count();
    let implicit_last = hidden.len() == indices.len() + 1;
    let explicit_last =
        hidden.len() == indices.len() && indices.last().is_some_and(|last| *last as usize == total);
    let unformatted = hidden.is_empty() && indices.is_empty();
    if !unformatted && !implicit_last && !explicit_last {
        return Err(Error::IncompleteNotebook);
    }
    if indices.windows(2).any(|pair| pair[0] > pair[1])
        || indices.last().is_some_and(|last| *last as usize > total)
    {
        return Err(Error::IncompleteNotebook);
    }
    let mut offset = 0;
    let mut run = 0;
    let mut previous_cr = false;
    for ch in text.chars() {
        while indices.get(run).is_some_and(|end| *end as usize == offset) {
            run += 1;
        }
        let next = offset + ch.len_utf16();
        if indices.get(run).is_some_and(|end| (*end as usize) < next) {
            return Err(Error::IncompleteNotebook);
        }
        let is_hidden = base_hidden || hidden.get(run).copied().unwrap_or(false);
        if !is_hidden {
            let normalized = match ch {
                '\r' => Some('\n'),
                '\n' if previous_cr => None,
                '\n' | '\u{000b}' | '\u{000c}' | '\u{0085}' | '\u{2028}' | '\u{2029}' => Some('\n'),
                '\t' => Some('\t'),
                value if value.is_control() => Some(' '),
                value if value.is_whitespace() => Some(' '),
                value => Some(value),
            };
            if let Some(ch) = normalized {
                output.character(ch)?;
            }
            previous_cr = ch == '\r';
        }
        offset = next;
    }
    Ok(())
}

fn rich_text(text: &RichText, output: &mut Text, excluded: &mut ExcludedContent) -> Result<()> {
    if !text.embedded_objects().is_empty()
        && text.embedded_objects().len() != text.text_run_formatting().len()
    {
        // Upstream clears paragraph text when it contains inline ink. If some
        // formatting runs are not represented by ink objects, typed text may
        // have been cleared as well; do not report a partial extraction.
        return Err(Error::IncompleteNotebook);
    }
    if text.math_inline_objects().iter().any(|object| {
        !matches!(
            object.object_type(),
            MathObjectType::SimpleText | MathObjectType::PlainText
        )
    }) {
        return Err(Error::UnsupportedFile);
    }
    for object in text.embedded_objects() {
        if matches!(object, EmbeddedObject::Ink(_)) {
            excluded.ink += 1;
        }
    }
    let hidden: Vec<_> = text
        .text_run_formatting()
        .iter()
        .map(|style| style.hidden())
        .collect();
    let previous_length = output.value.len();
    visible_runs(
        text.text(),
        text.text_run_indices(),
        &hidden,
        text.paragraph_style().hidden(),
        output,
    )?;
    if output.value.len() > previous_length {
        output.push("\n")?;
    }
    Ok(())
}

fn table_cell(value: &str, output: &mut Text) -> Result<()> {
    if value.trim().is_empty() {
        return Ok(());
    }
    if value.contains(['\t', '\n', '"']) {
        output.push("\"")?;
        for part in value.split_inclusive('"') {
            output.push(part)?;
            if part.ends_with('"') {
                output.push("\"")?;
            }
        }
        output.push("\"")
    } else {
        output.push(value)
    }
}

fn element(
    item: &OutlineElement,
    output: &mut Text,
    excluded: &mut ExcludedContent,
    nesting: usize,
) -> Result<()> {
    depth(nesting)?;
    for content in item.contents() {
        match content {
            Content::RichText(text) => rich_text(text, output, excluded)?,
            Content::Table(table) => {
                depth(nesting + 1)?;
                if table.rows() as usize != table.contents().len()
                    || table
                        .contents()
                        .iter()
                        .any(|row| row.contents().len() != table.cols() as usize)
                {
                    return Err(Error::IncompleteNotebook);
                }
                for row in table.contents() {
                    for (index, cell) in row.contents().iter().enumerate() {
                        if index != 0 {
                            output.push("\t")?;
                        }
                        let mut value = Text::new(output.remaining());
                        for item in cell.contents() {
                            element(item, &mut value, excluded, nesting + 2)?;
                        }
                        table_cell(&value.finish(), output)?;
                    }
                    output.push("\n")?;
                }
            }
            Content::Image(_) => excluded.images += 1,
            Content::Ink(_) => excluded.ink += 1,
            Content::EmbeddedFile(_) => excluded.attachments += 1,
            Content::Unknown => return Err(Error::UnsupportedFile),
        }
    }
    if !item.children().is_empty() {
        outline(item.children(), output, excluded, nesting + 1)?;
    }
    Ok(())
}

pub(crate) fn outline(
    items: &[OutlineItem],
    output: &mut Text,
    excluded: &mut ExcludedContent,
    nesting: usize,
) -> Result<()> {
    depth(nesting)?;
    for item in items {
        match item {
            OutlineItem::Element(item) => element(item, output, excluded, nesting)?,
            OutlineItem::Group(group) => outline(group.outlines(), output, excluded, nesting + 1)?,
        }
    }
    Ok(())
}

pub(crate) fn page(
    contents: &[PageContent],
    output: &mut Text,
    excluded: &mut ExcludedContent,
) -> Result<()> {
    for content in contents {
        match content {
            PageContent::Outline(value) => outline(value.items(), output, excluded, 1)?,
            PageContent::Image(_) => excluded.images += 1,
            PageContent::Ink(_) => excluded.ink += 1,
            PageContent::EmbeddedFile(_) => excluded.attachments += 1,
            PageContent::Unknown => return Err(Error::UnsupportedFile),
        }
    }
    Ok(())
}

pub(crate) fn excluded_warning(message: &str) -> bool {
    matches!(
        message,
        "embedded file has no filename; preserving it as unavailable"
            | "embedded file has no data container; preserving file metadata"
            | "embedded file payload is marked invalid; preserving file metadata"
            | "image payload is marked invalid; preserving image metadata"
            | "maximum recognized-text nesting depth exceeded"
    ) || (message.starts_with("ink data object ") && message.ends_with(" not found, skipping ink"))
        || (message.starts_with("recognized text root ") && message.ends_with(" is missing"))
        || (message.starts_with("recognized text node ") && message.ends_with(" is missing"))
        || message.starts_with("page recognized-text reference ")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn visible(text: &str, indices: &[u32], hidden: &[bool]) -> Result<String> {
        let mut output = Text::new(1024);
        visible_runs(text, indices, hidden, false, &mut output)?;
        Ok(output.finish())
    }

    #[test]
    fn hides_utf16_runs_without_losing_supplementary_characters() {
        let text = "😀secret中Visible🌻";
        let result = visible(text, &[2, 9], &[false, true, false]).unwrap();
        assert_eq!(result, "😀Visible🌻");
    }

    #[test]
    fn visible_marker_like_prose_is_not_heuristically_removed() {
        let literal = "HYPERLINK \"literal typed words\"";
        let result = visible(literal, &[], &[false]).unwrap();
        assert_eq!(result, literal);
        let hidden = visible("hiddenvisible", &[6], &[true, false]).unwrap();
        assert_eq!(hidden, "visible");
    }

    #[test]
    fn validates_every_utf16_boundary_and_style_count() {
        for (indices, hidden) in [
            (vec![1], vec![true, false]),
            (vec![4, 2], vec![true, false, false]),
            (vec![99], vec![false, false]),
            (vec![2], vec![]),
            (vec![], vec![false, false]),
        ] {
            let result = visible("😀abc", &indices, &hidden);
            assert_eq!(result, Err(Error::IncompleteNotebook));
        }
    }

    #[test]
    fn supports_empty_runs_explicit_ends_and_whole_paragraph_hidden() {
        let empty_runs = visible("abc", &[0, 1, 3], &[true, false, true]).unwrap();
        let whole = visible("abc", &[], &[true]).unwrap();
        let plain = visible("abc", &[], &[]).unwrap();
        let mut output = Text::new(100);
        visible_runs("abc", &[], &[false], true, &mut output).unwrap();
        assert_eq!(empty_runs, "a");
        assert_eq!(whole, "");
        assert_eq!(plain, "abc");
        assert_eq!(output.finish(), "");
    }

    #[test]
    fn normalizes_visible_plain_text_without_html_serialization() {
        let result = visible(
            "a\r\nb\rc\u{000b}d\u{00a0}e\tf\u{0000}<b>typed</b>",
            &[],
            &[],
        )
        .unwrap();
        assert_eq!(result, "a\nb\nc\nd e\tf <b>typed</b>");
    }

    #[test]
    fn preserves_table_empty_cells_and_multiline_cell_boundaries() {
        let mut output = Text::new(1024);
        table_cell("", &mut output).unwrap();
        output.push("\t").unwrap();
        table_cell("one\ntwo \"quoted\"", &mut output).unwrap();
        output.push("\tlast\n").unwrap();
        assert_eq!(output.finish(), "\t\"one\ntwo \"\"quoted\"\"\"\tlast");
    }

    #[test]
    fn whitespace_only_cells_do_not_manufacture_visible_quote_characters() {
        let mut output = Text::new(100);
        table_cell(" \t\n ", &mut output).unwrap();
        let text = output.finish();
        assert!(text.is_empty());
    }

    #[test]
    fn bounds_text_during_writes_and_recursion_before_visiting_children() {
        let mut output = Text::new(3);
        let too_much = visible_runs("😀", &[], &[], false, &mut output);
        let deep = outline(
            &[],
            &mut output,
            &mut ExcludedContent::default(),
            MAX_DEPTH + 1,
        );
        assert_eq!(too_much, Err(Error::LimitExceeded));
        assert_eq!(deep, Err(Error::LimitExceeded));
    }

    #[test]
    fn unknown_page_content_is_not_silently_dropped() {
        let result = page(
            &[PageContent::Unknown],
            &mut Text::new(100),
            &mut ExcludedContent::default(),
        );
        assert_eq!(result, Err(Error::UnsupportedFile));
    }

    #[test]
    fn only_excluded_media_warnings_are_ignorable() {
        assert!(excluded_warning(
            "image payload is marked invalid; preserving image metadata"
        ));
        assert!(!excluded_warning(
            "missing style for text run formatting: untrusted"
        ));
        assert!(!excluded_warning("failed to import section untrusted"));
    }
}
