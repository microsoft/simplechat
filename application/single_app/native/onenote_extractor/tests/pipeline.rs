// pipeline.rs
//! Native protocol v1 / helper 0.1.0 integration tests.
//! Public OneNote fixtures are attributed in fixtures/SOURCES.txt.
//! CABs assembled here are deterministic test containers, not desktop exports.

use std::io::{Cursor, Write};
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};

use bytes::Bytes;
use simplechat_onenote_extractor::error::Error;
use simplechat_onenote_extractor::extract;
use simplechat_onenote_extractor::limits::PARSER_REVISION;

fn fixture(name: &str) -> Vec<u8> {
    let mut path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures");
    for part in name.split('\\') {
        path.push(part);
    }
    std::fs::read(path).unwrap()
}

fn cabinet(files: &[(&str, Vec<u8>)], compression: cab::CompressionType) -> Vec<u8> {
    let mut builder = cab::CabinetBuilder::new();
    let folder = builder.add_folder(compression);
    for (name, _) in files {
        folder.add_file((*name).to_owned());
    }
    let mut writer = builder.build(Cursor::new(Vec::new())).unwrap();
    let mut index = 0;
    while let Some(mut file) = writer.next_file().unwrap() {
        file.write_all(&files[index].1).unwrap();
        index += 1;
    }
    writer.finish().unwrap().into_inner()
}

fn single_section_package() -> Vec<(&'static str, Vec<u8>)> {
    vec![
        ("Open Notebook.onetoc2", fixture("Open Notebook.onetoc2")),
        ("New Section 1.one", fixture("New Section 1.one")),
    ]
}

fn nested_package() -> Vec<(&'static str, Vec<u8>)> {
    vec![
        ("Open Notebook.onetoc2", fixture("Open Notebook.onetoc2")),
        (
            "New Section 1.one\\Open Notebook.onetoc2",
            fixture("New Section Group\\Open Notebook.onetoc2"),
        ),
        (
            "New Section 1.one\\New Section 1.one",
            fixture("New Section Group\\New Section 1.one"),
        ),
        (
            "New Section 1.one\\New Section 2.one",
            fixture("New Section Group\\New Section 2.one"),
        ),
    ]
}

struct InputFile(PathBuf);

impl InputFile {
    fn new(name: &str, bytes: &[u8]) -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let directory = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("target")
            .join("native-test-inputs")
            .join(format!(
                "{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
        std::fs::create_dir_all(&directory).unwrap();
        let path = directory.join(name);
        std::fs::write(&path, bytes).unwrap();
        Self(path)
    }
}

impl Drop for InputFile {
    fn drop(&mut self) {
        if let Some(directory) = self.0.parent() {
            let _ = std::fs::remove_dir_all(directory);
        }
    }
}

#[test]
fn real_public_section_preserves_visible_unicode_tables_and_media_counts() {
    let document = extract::section(Bytes::from(fixture("New Section 1.one"))).unwrap();
    assert_eq!(document.sections, 1);
    assert_eq!(document.source_pages, document.pages.len());
    assert_eq!(document.pages[0].title, "Test Page");
    let text = &document.pages[0].text;
    assert!(text.contains("A\tB\tC\n1\t2\t3"));
    assert!(text.contains("𝑎=𝑏"));
    assert!(!text.contains("\u{fddf}HYPERLINK"));
    assert!(document.excluded_content.images > 0);
    assert_eq!(document.parser_revision, PARSER_REVISION);
}

#[test]
fn generated_uncompressed_and_mszip_packages_match_real_section_text() {
    let standalone = extract::section(Bytes::from(fixture("New Section 1.one"))).unwrap();
    for compression in [cab::CompressionType::None, cab::CompressionType::MsZip] {
        let bytes = cabinet(&single_section_package(), compression);
        let package = extract::package(&bytes).unwrap();
        assert_eq!(package.sections, 1);
        assert_eq!(package.pages[0].text, standalone.pages[0].text);
        assert_eq!(package.pages[0].id, standalone.pages[0].id);
    }
}

#[test]
fn source_filename_is_only_a_missing_metadata_fallback() {
    let bytes = Bytes::from(fixture("New Section 1.one"));
    let default = extract::section(bytes.clone()).unwrap();
    let friendly =
        extract::section_with_source_filename(bytes, Some("Original Café 😀.ONE")).unwrap();
    assert_eq!(default.pages[0].section_path, ["section"]);
    assert_eq!(friendly.pages[0].section_path, ["Original Café 😀"]);
    assert_eq!(friendly.pages[0].text, default.pages[0].text);
    assert_eq!(friendly.pages[0].id, default.pages[0].id);
}

#[test]
fn genuine_stored_section_name_wins_over_source_filename() {
    let bytes = Bytes::from(fixture("Schnelle Notizen.one"));
    let default = extract::section(bytes.clone()).unwrap();
    let friendly =
        extract::section_with_source_filename(bytes, Some("Do not overwrite stored metadata.one"))
            .unwrap();
    assert!(!friendly.pages.is_empty());
    assert!(
        friendly
            .pages
            .iter()
            .all(|page| page.section_path == ["Scribbles"])
    );
    let default_json = extract::serialize(&default).unwrap();
    let friendly_json = extract::serialize(&friendly).unwrap();
    assert_eq!(friendly_json, default_json);
}

#[test]
fn cli_never_uses_random_input_basename_as_section_context() {
    let input = InputFile::new("random-upload-8eb5049b.one", &fixture("New Section 1.one"));
    let executable = env!("CARGO_BIN_EXE_simplechat-onenote-extractor");
    let default = Command::new(executable).arg(&input.0).output().unwrap();
    let friendly = Command::new(executable)
        .arg(&input.0)
        .arg("Original upload.ONE")
        .output()
        .unwrap();
    assert!(default.status.success());
    assert!(friendly.status.success());
    assert!(default.stderr.is_empty());
    assert!(friendly.stderr.is_empty());
    let default_json: serde_json::Value = serde_json::from_slice(&default.stdout).unwrap();
    let friendly_json: serde_json::Value = serde_json::from_slice(&friendly.stdout).unwrap();
    assert_eq!(
        default_json["pages"][0]["section_path"],
        serde_json::json!(["section"])
    );
    assert_eq!(
        friendly_json["pages"][0]["section_path"],
        serde_json::json!(["Original upload"])
    );
    assert_eq!(
        friendly_json["pages"][0]["text"],
        default_json["pages"][0]["text"]
    );
}

#[test]
fn package_cli_accepts_but_ignores_original_filename() {
    let bytes = cabinet(&nested_package(), cab::CompressionType::MsZip);
    let input = InputFile::new("random-package.onepkg", &bytes);
    let executable = env!("CARGO_BIN_EXE_simplechat-onenote-extractor");
    let default = Command::new(executable).arg(&input.0).output().unwrap();
    let friendly = Command::new(executable)
        .arg(&input.0)
        .arg("Do not rename groups.ONEPKG")
        .output()
        .unwrap();
    assert!(default.status.success());
    assert!(friendly.status.success());
    assert!(friendly.stderr.is_empty());
    assert_eq!(friendly.stdout, default.stdout);
}

#[test]
fn source_filename_arguments_reject_paths_and_excess_arguments_safely() {
    let input = InputFile::new("source.one", &fixture("New Section 1.one"));
    let executable = env!("CARGO_BIN_EXE_simplechat-onenote-extractor");
    for label in ["../private.one", "C:\\private.one", "secret\nname.one", ""] {
        let output = Command::new(executable)
            .arg(&input.0)
            .arg(label)
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stderr.is_empty());
        assert_eq!(output.stdout, Error::InvalidFile.response());
    }
    let too_many = Command::new(executable)
        .arg(&input.0)
        .args(["Label.one", "extra"])
        .output()
        .unwrap();
    let version_with_label = Command::new(executable)
        .args(["--version", "Label.one"])
        .output()
        .unwrap();
    assert_eq!(too_many.status.code(), Some(2));
    assert_eq!(version_with_label.status.code(), Some(2));
    assert_eq!(too_many.stdout, Error::InvalidFile.response());
    assert_eq!(version_with_label.stdout, Error::InvalidFile.response());
}

#[test]
fn missing_live_sections_fail_instead_of_returning_partial_notebooks() {
    let mut files = single_section_package();
    files.pop();
    let bytes = cabinet(&files, cab::CompressionType::MsZip);
    let result = extract::package(&bytes);
    assert!(matches!(result, Err(Error::IncompleteNotebook)));
}

#[test]
fn live_unreferenced_sections_fail_inventory_coverage() {
    let mut files = single_section_package();
    files.push((
        "Unreferenced.one",
        fixture("New Section Group\\New Section 1.one"),
    ));
    let bytes = cabinet(&files, cab::CompressionType::MsZip);
    let result = extract::package(&bytes);
    assert!(matches!(result, Err(Error::IncompleteNotebook)));
}

#[test]
fn nested_section_hierarchy_survives_and_nested_parse_failures_are_fatal() {
    let files = nested_package();
    let bytes = cabinet(&files, cab::CompressionType::MsZip);
    let document = extract::package(&bytes).unwrap();
    assert_eq!(document.sections, 2);
    assert!(
        document
            .pages
            .iter()
            .all(|page| page.section_path.len() == 2)
    );

    let mut broken = files;
    let last = broken.last_mut().unwrap();
    last.1.truncate(64);
    let bytes = cabinet(&broken, cab::CompressionType::MsZip);
    let result = extract::package(&bytes);
    assert!(matches!(result, Err(Error::IncompleteNotebook)));
}

#[test]
fn nested_missing_section_is_not_lost_with_nested_warning_report() {
    let mut files = nested_package();
    files.pop();
    let bytes = cabinet(&files, cab::CompressionType::MsZip);
    let result = extract::package(&bytes);
    assert!(matches!(result, Err(Error::IncompleteNotebook)));
}

#[test]
fn nested_empty_group_parse_failure_is_fatal_even_when_all_sections_succeed() {
    let mut broken_toc = fixture("Open Notebook.onetoc2");
    broken_toc.truncate(64);
    let files = vec![
        ("Open Notebook.onetoc2", fixture("Open Notebook.onetoc2")),
        (
            "New Section 1.one\\Open Notebook.onetoc2",
            fixture("New Section Group\\Open Notebook.onetoc2"),
        ),
        (
            "New Section 1.one\\New Section 1.one\\Open Notebook.onetoc2",
            broken_toc,
        ),
        (
            "New Section 1.one\\New Section 2.one",
            fixture("New Section Group\\New Section 2.one"),
        ),
    ];
    let bytes = cabinet(&files, cab::CompressionType::MsZip);
    let result = extract::package(&bytes);
    assert!(matches!(result, Err(Error::IncompleteNotebook)));
}

#[test]
fn recycle_bin_is_ignored_but_arbitrary_old_named_sections_are_not() {
    let mut files = single_section_package();
    files.push(("OneNote_RecycleBin\\Bad.one", b"not a section".to_vec()));
    files.push(("OneNote_RecycleBin\\Open.onetoc2", b"not a toc".to_vec()));
    files.push(("ignored.bin", b"not executed or ingested".to_vec()));
    let bytes = cabinet(&files, cab::CompressionType::MsZip);
    let document = extract::package(&bytes).unwrap();
    assert_eq!(document.sections, 1);
    assert_eq!(document.excluded_content.attachments, 1);
    files.push(("Old\\Bad.one", b"not a section".to_vec()));
    let bytes = cabinet(&files, cab::CompressionType::MsZip);
    let result = extract::package(&bytes);
    assert!(result.is_err());
}

#[test]
fn windows_case_insensitive_members_and_uppercase_toc_extensions_work() {
    let mut files = nested_package();
    files[1].0 = "New Section 1.one\\Open Notebook.ONETOC2";
    files[2].0 = "NEW SECTION 1.ONE\\NEW SECTION 1.ONE";
    let bytes = cabinet(&files, cab::CompressionType::MsZip);
    let document = extract::package(&bytes).unwrap();
    assert_eq!(document.sections, 2);
}

#[test]
fn cli_contract_is_stable_and_does_not_expose_failure_paths() {
    let executable = env!("CARGO_BIN_EXE_simplechat-onenote-extractor");
    let file = InputFile::new("never-print-this-private-name.ONE", b"malformed input");
    let output = Command::new(executable).arg(&file.0).output().unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stderr.is_empty());
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        response,
        serde_json::json!({
            "protocol_version": 1, "error": {"code": "invalid_file"}
        })
    );

    let relative = Command::new(executable)
        .arg("relative.one")
        .output()
        .unwrap();
    assert_eq!(relative.status.code(), Some(2));
    assert!(relative.stderr.is_empty());
    let version = Command::new(executable).arg("--version").output().unwrap();
    assert!(version.status.success());
    assert!(version.stderr.is_empty());
    assert!(
        String::from_utf8(version.stdout)
            .unwrap()
            .contains(PARSER_REVISION)
    );
}

#[test]
fn actual_cli_emits_one_bounded_success_object() {
    let file = InputFile::new("section.ONE", &fixture("New Section 1.one"));
    let output = Command::new(env!("CARGO_BIN_EXE_simplechat-onenote-extractor"))
        .arg(&file.0)
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(response["protocol_version"], 1);
    assert_eq!(response["parser_revision"], PARSER_REVISION);
    assert!(response.get("error").is_none());
    assert_eq!(
        response["source_pages"].as_u64().unwrap() as usize,
        response["pages"].as_array().unwrap().len()
    );
}

#[cfg(target_os = "linux")]
#[test]
fn supervisor_handles_an_inherited_ignored_child_signal() {
    use std::os::unix::process::CommandExt;

    let file = InputFile::new("signal.one", b"invalid file");
    let mut command = Command::new(env!("CARGO_BIN_EXE_simplechat-onenote-extractor"));
    command.arg(&file.0);
    // SAFETY: the pre-exec test hook performs only async-signal-safe signal
    // setup, with no allocation, locks, or application callbacks.
    unsafe {
        command.pre_exec(|| {
            if libc::signal(libc::SIGCHLD, libc::SIG_IGN) == libc::SIG_ERR {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    let output = command.output().unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stderr.is_empty());
    let response: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(response["error"]["code"], "invalid_file");
}
