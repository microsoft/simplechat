// package.rs

use std::collections::{BTreeMap, BTreeSet};
use std::io::{self, Read, Seek, SeekFrom};
use std::ops::Range;

use bytes::Bytes;

use crate::error::{Error, Result};
use crate::limits::{
    IO_CHUNK_BYTES, MAX_CAB_BLOCKS, MAX_COMPONENT_CHARS, MAX_DEPTH, MAX_EXPANDED_BYTES,
    MAX_INPUT_BYTES, MAX_MEMBER_BYTES, MAX_MEMBERS,
};
use crate::paths::{MemberPath, inside};

pub(crate) struct Archive {
    pub files: Vec<(MemberPath, Bytes)>,
    pub root_toc: String,
    pub root_directory: String,
    pub attachments: usize,
}

#[derive(Debug)]
struct Member {
    path: MemberPath,
    folder: usize,
    offset: usize,
    size: usize,
}

#[derive(Debug)]
struct Folder {
    range: Range<usize>,
    blocks: u16,
    compression: u16,
    expanded: usize,
}

struct Plan {
    members: Vec<Member>,
    folders: Vec<Folder>,
    data_reserve: u8,
    root_toc: String,
    root_directory: String,
}

struct Raw<'a> {
    data: &'a [u8],
    position: usize,
}

impl<'a> Raw<'a> {
    fn take(&mut self, size: usize) -> Result<&'a [u8]> {
        let end = self
            .position
            .checked_add(size)
            .ok_or(Error::UnsafePackage)?;
        let bytes = self
            .data
            .get(self.position..end)
            .ok_or(Error::UnsafePackage)?;
        self.position = end;
        Ok(bytes)
    }

    fn u8(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }

    fn u16(&mut self) -> Result<u16> {
        let bytes = self.take(2)?;
        Ok(u16::from_le_bytes([bytes[0], bytes[1]]))
    }

    fn u32(&mut self) -> Result<u32> {
        let bytes = self.take(4)?;
        Ok(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
    }

    fn name(&mut self) -> Result<MemberPath> {
        let remaining = self.data.get(self.position..).ok_or(Error::UnsafePackage)?;
        let max_bytes = MAX_DEPTH * (MAX_COMPONENT_CHARS * 4 + 1);
        let end = remaining
            .iter()
            .take(max_bytes + 1)
            .position(|byte| *byte == 0)
            .ok_or(Error::LimitExceeded)?;
        let name = std::str::from_utf8(self.take(end)?).map_err(|_| Error::UnsafePackage)?;
        self.take(1)?;
        MemberPath::parse(name)
    }
}

fn add_expansion(total: &mut usize, size: usize) -> Result<()> {
    *total = total.checked_add(size).ok_or(Error::LimitExceeded)?;
    if *total > MAX_EXPANDED_BYTES {
        return Err(Error::LimitExceeded);
    }
    Ok(())
}

fn root_and_collisions(members: &[Member]) -> Result<(String, String)> {
    let mut files = BTreeSet::new();
    let mut directories = BTreeSet::new();
    let mut tocs = BTreeMap::new();
    for member in members {
        let path = &member.path;
        if !files.insert(path.key.clone()) {
            return Err(Error::UnsafePackage);
        }
        for (index, _) in path.key.match_indices('\\') {
            directories.insert(path.key[..index].to_owned());
        }
        if path.is_payload()
            && path.is_toc()
            && tocs.insert(path.parent_key(), &path.name).is_some()
        {
            return Err(Error::UnsafePackage);
        }
    }
    if !files.is_disjoint(&directories) {
        return Err(Error::UnsafePackage);
    }
    let root = members
        .iter()
        .filter(|member| member.path.is_payload() && member.path.is_toc())
        .min_by_key(|member| member.path.components.len())
        .ok_or(Error::UnsafePackage)?;
    let root_directory = root.path.parent_key();
    if members
        .iter()
        .any(|member| member.path.is_payload() && !inside(&member.path.key, root_directory))
    {
        return Err(Error::UnsafePackage);
    }
    for member in members.iter().filter(|member| member.path.is_payload()) {
        let mut directory = member.path.parent_key();
        while directory != root_directory {
            if !tocs.contains_key(directory) {
                return Err(Error::IncompleteNotebook);
            }
            directory = directory.rsplit_once('\\').map_or("", |(parent, _)| parent);
        }
    }
    Ok((root.path.name.clone(), root_directory.to_owned()))
}

fn preflight(data: &[u8]) -> Result<Plan> {
    if data.len() > MAX_INPUT_BYTES {
        return Err(Error::LimitExceeded);
    }
    if data.len() < 36 || &data[..4] != b"MSCF" {
        return Err(Error::InvalidFile);
    }
    let mut raw = Raw { data, position: 4 };
    if raw.u32()? != 0 {
        return Err(Error::UnsafePackage);
    }
    let cabinet_size = raw.u32()? as usize;
    if cabinet_size != data.len() || raw.u32()? != 0 {
        return Err(Error::UnsafePackage);
    }
    let files_offset = raw.u32()? as usize;
    if raw.u32()? != 0 {
        return Err(Error::UnsafePackage);
    }
    if raw.u8()? != 3 || raw.u8()? != 1 {
        return Err(Error::UnsupportedFile);
    }
    let folder_count = raw.u16()? as usize;
    let file_count = raw.u16()? as usize;
    if folder_count > MAX_MEMBERS || file_count > MAX_MEMBERS {
        return Err(Error::LimitExceeded);
    }
    if folder_count == 0 || file_count == 0 {
        return Err(Error::UnsafePackage);
    }
    let flags = raw.u16()?;
    raw.u16()?;
    if flags & !4 != 0 || raw.u16()? != 0 {
        return Err(Error::UnsafePackage);
    }
    let (folder_reserve, data_reserve) = if flags == 4 {
        let header_reserve = raw.u16()? as usize;
        let folder_reserve = raw.u8()? as usize;
        let data_reserve = raw.u8()?;
        raw.take(header_reserve)?;
        (folder_reserve, data_reserve)
    } else {
        (0, 0)
    };
    let mut folders = Vec::with_capacity(folder_count);
    let mut block_count = 0usize;
    for _ in 0..folder_count {
        let start = raw.u32()? as usize;
        let blocks = raw.u16()?;
        let compression = raw.u16()?;
        match compression & 15 {
            0 | 1 if compression <= 1 => {}
            3 if compression & !0x1f03 == 0 && (15..=25).contains(&(compression >> 8)) => {}
            _ => return Err(Error::UnsupportedFile),
        }
        block_count += blocks as usize;
        if block_count > MAX_CAB_BLOCKS {
            return Err(Error::LimitExceeded);
        }
        raw.take(folder_reserve)?;
        folders.push(Folder {
            range: start..start,
            blocks,
            compression,
            expanded: 0,
        });
    }
    if files_offset < raw.position || files_offset > data.len() {
        return Err(Error::UnsafePackage);
    }
    raw.position = files_offset;
    let mut members = Vec::with_capacity(file_count);
    let mut member_bytes = 0;
    for _ in 0..file_count {
        let size = raw.u32()? as usize;
        let offset = raw.u32()? as usize;
        let folder = raw.u16()? as usize;
        raw.take(4)?;
        let attributes = raw.u16()?;
        if size > MAX_MEMBER_BYTES {
            return Err(Error::LimitExceeded);
        }
        add_expansion(&mut member_bytes, size)?;
        if folder >= folder_count || attributes & 0x10 != 0 {
            return Err(Error::UnsafePackage);
        }
        let path = raw.name()?;
        members.push(Member {
            path,
            folder,
            offset,
            size,
        });
    }
    let metadata_end = raw.position;
    let (root_toc, root_directory) = root_and_collisions(&members)?;
    let mut folder_bytes = 0;
    for folder in &mut folders {
        if folder.range.start < metadata_end || folder.range.start > data.len() {
            return Err(Error::UnsafePackage);
        }
        raw.position = folder.range.start;
        for _ in 0..folder.blocks {
            raw.u32()?;
            let compressed = raw.u16()? as usize;
            let expanded = raw.u16()? as usize;
            if compressed == 0 || expanded == 0 || expanded > IO_CHUNK_BYTES {
                return Err(Error::UnsafePackage);
            }
            if folder.compression == 0 && compressed != expanded {
                return Err(Error::UnsafePackage);
            }
            add_expansion(&mut folder_bytes, expanded)?;
            folder.expanded += expanded;
            raw.take(data_reserve as usize)?;
            raw.take(compressed)?;
        }
        folder.range.end = raw.position;
    }
    let mut ranges: Vec<_> = folders.iter().map(|folder| folder.range.clone()).collect();
    ranges.sort_by_key(|range| range.start);
    if ranges.windows(2).any(|pair| pair[0].end > pair[1].start) {
        return Err(Error::UnsafePackage);
    }
    for (index, folder) in folders.iter().enumerate() {
        let mut members: Vec<_> = members
            .iter()
            .filter(|member| member.folder == index)
            .collect();
        members.sort_by_key(|member| member.offset);
        let mut end = 0;
        for member in members {
            let next = member
                .offset
                .checked_add(member.size)
                .ok_or(Error::UnsafePackage)?;
            if member.offset < end || next > folder.expanded {
                return Err(Error::UnsafePackage);
            }
            end = next;
        }
    }
    Ok(Plan {
        members,
        folders,
        data_reserve,
        root_toc,
        root_directory,
    })
}

// cab's public file reader replays a compression folder from its beginning for
// every member. A synthetic, validated directory exposes each selected folder
// once, without copying its compressed bytes or materializing attachments.
struct FolderCab<'a> {
    header: Vec<u8>,
    segments: Vec<&'a [u8]>,
    position: usize,
    length: usize,
}

impl<'a> FolderCab<'a> {
    fn new(data: &'a [u8], plan: &Plan, selected: &[usize]) -> Self {
        let reserve = usize::from(plan.data_reserve != 0) * 4;
        let files_offset = 36 + reserve + selected.len() * 8;
        let file_names: Vec<_> = (0..selected.len()).map(|i| format!("folder-{i}")).collect();
        let header_size =
            files_offset + file_names.iter().map(|name| 17 + name.len()).sum::<usize>();
        let length = header_size
            + selected
                .iter()
                .map(|index| plan.folders[*index].range.len())
                .sum::<usize>();
        let mut header = Vec::with_capacity(header_size);
        header.extend_from_slice(b"MSCF");
        header.extend_from_slice(&0u32.to_le_bytes());
        header.extend_from_slice(&(length as u32).to_le_bytes());
        header.extend_from_slice(&0u32.to_le_bytes());
        header.extend_from_slice(&(files_offset as u32).to_le_bytes());
        header.extend_from_slice(&0u32.to_le_bytes());
        header.extend_from_slice(&[3, 1]);
        header.extend_from_slice(&(selected.len() as u16).to_le_bytes());
        header.extend_from_slice(&(selected.len() as u16).to_le_bytes());
        header.extend_from_slice(&(if reserve != 0 { 4u16 } else { 0 }).to_le_bytes());
        header.extend_from_slice(&[0; 4]);
        if reserve != 0 {
            header.extend_from_slice(&[0, 0, 0, plan.data_reserve]);
        }
        let mut offset = header_size;
        let mut segments = Vec::new();
        for index in selected {
            let folder = &plan.folders[*index];
            header.extend_from_slice(&(offset as u32).to_le_bytes());
            header.extend_from_slice(&folder.blocks.to_le_bytes());
            header.extend_from_slice(&folder.compression.to_le_bytes());
            let segment = &data[folder.range.clone()];
            offset += segment.len();
            segments.push(segment);
        }
        for (index, name) in file_names.iter().enumerate() {
            let folder = &plan.folders[selected[index]];
            header.extend_from_slice(&(folder.expanded as u32).to_le_bytes());
            header.extend_from_slice(&0u32.to_le_bytes());
            header.extend_from_slice(&(index as u16).to_le_bytes());
            header.extend_from_slice(&[0; 6]);
            header.extend_from_slice(name.as_bytes());
            header.push(0);
        }
        Self {
            header,
            segments,
            position: 0,
            length,
        }
    }
}

impl Read for FolderCab<'_> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        let mut start = 0;
        for segment in std::iter::once(self.header.as_slice()).chain(self.segments.iter().copied())
        {
            let end = start + segment.len();
            if self.position < end {
                let offset = self.position - start;
                let size = output.len().min(segment.len() - offset);
                output[..size].copy_from_slice(&segment[offset..offset + size]);
                self.position += size;
                return Ok(size);
            }
            start = end;
        }
        Ok(0)
    }
}

impl Seek for FolderCab<'_> {
    fn seek(&mut self, position: SeekFrom) -> io::Result<u64> {
        let position = match position {
            SeekFrom::Start(offset) => i128::from(offset),
            SeekFrom::End(offset) => self.length as i128 + i128::from(offset),
            SeekFrom::Current(offset) => self.position as i128 + i128::from(offset),
        };
        self.position =
            usize::try_from(position).map_err(|_| io::Error::from(io::ErrorKind::InvalidInput))?;
        Ok(self.position as u64)
    }
}

fn read_exact(reader: &mut impl Read, bytes: &mut [u8], actual: &mut usize) -> Result<()> {
    for chunk in bytes.chunks_mut(IO_CHUNK_BYTES) {
        reader.read_exact(chunk).map_err(|_| Error::UnsafePackage)?;
        add_expansion(actual, chunk.len())?;
    }
    Ok(())
}

pub(crate) fn extract(data: &[u8]) -> Result<Archive> {
    let plan = preflight(data)?;
    let selected: Vec<_> = (0..plan.folders.len())
        .filter(|folder| {
            plan.members
                .iter()
                .any(|member| member.folder == *folder && member.path.is_payload())
        })
        .collect();
    let reader = FolderCab::new(data, &plan, &selected);
    let mut cabinet = cab::Cabinet::new(reader).map_err(|_| Error::UnsafePackage)?;
    let mut actual = 0;
    let mut files = Vec::new();
    let mut scratch = [0; IO_CHUNK_BYTES];
    for (index, folder) in selected.iter().enumerate() {
        let mut members: Vec<_> = plan
            .members
            .iter()
            .filter(|member| member.folder == *folder && member.path.is_payload())
            .collect();
        members.sort_by_key(|member| member.offset);
        let mut reader = cabinet
            .read_file(&format!("folder-{index}"))
            .map_err(|_| Error::UnsafePackage)?;
        let mut position = 0;
        for member in members {
            if member.size == 0 {
                return Err(Error::InvalidFile);
            }
            while position < member.offset {
                let size = scratch.len().min(member.offset - position);
                read_exact(&mut reader, &mut scratch[..size], &mut actual)?;
                position += size;
            }
            let mut bytes = Vec::new();
            bytes
                .try_reserve_exact(member.size)
                .map_err(|_| Error::LimitExceeded)?;
            bytes.resize(member.size, 0);
            read_exact(&mut reader, &mut bytes, &mut actual)?;
            position += member.size;
            crate::signature::validate(&bytes, member.path.is_toc())?;
            files.push((member.path.clone(), Bytes::from(bytes)));
        }
    }
    let attachments = plan
        .members
        .iter()
        .filter(|member| {
            !member.path.recycle_bin && !member.path.is_section() && !member.path.is_toc()
        })
        .count();
    Ok(Archive {
        files,
        root_toc: plan.root_toc,
        root_directory: plan.root_directory,
        attachments,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Cursor, Write};

    fn cab(names: &[&str], data: &[u8]) -> Vec<u8> {
        let mut builder = cab::CabinetBuilder::new();
        let folder = builder.add_folder(cab::CompressionType::None);
        for name in names {
            folder.add_file(name.to_string());
        }
        let mut writer = builder.build(Cursor::new(Vec::new())).unwrap();
        while let Some(mut file) = writer.next_file().unwrap() {
            file.write_all(data).unwrap();
        }
        writer.finish().unwrap().into_inner()
    }

    fn failure(bytes: &[u8]) -> Error {
        match preflight(bytes) {
            Ok(_) => panic!("unsafe cabinet was accepted"),
            Err(error) => error,
        }
    }

    #[test]
    fn preflights_valid_cab_without_decompressing() {
        let bytes = cab(&["Book\\Open.onetoc2", "Book\\Section.one"], b"data");
        let plan = preflight(&bytes).unwrap();
        assert_eq!(plan.members.len(), 2);
        assert_eq!(plan.root_directory, "BOOK");
        assert_eq!(plan.folders[0].expanded, 8);
    }

    #[test]
    fn rejects_traversal_and_case_or_directory_collisions() {
        for names in [
            vec!["Open.onetoc2", "..\\Escape.one"],
            vec!["Open.onetoc2", "A.one", "a.ONE"],
            vec!["Open.onetoc2", "a.one", "a.one\\b.one"],
            vec!["Open.onetoc2", "Group\\a.one", "group"],
            vec!["Open.onetoc2", "\\\\host\\secret.one"],
        ] {
            let bytes = cab(&names, b"data");
            let error = failure(&bytes);
            assert_eq!(error, Error::UnsafePackage);
        }
    }

    #[test]
    fn rejects_ambiguous_roots_and_unscoped_sections() {
        for names in [
            vec!["a.onetoc2", "b.onetoc2"],
            vec!["a\\Open.onetoc2", "b\\Open.onetoc2"],
            vec!["a\\Open.onetoc2", "b\\s.one"],
            vec!["no-toc.one"],
        ] {
            let bytes = cab(&names, b"data");
            let error = failure(&bytes);
            assert_eq!(error, Error::UnsafePackage);
        }
    }

    #[test]
    fn rejects_unmanifested_group_hierarchies() {
        for names in [
            vec!["Open.onetoc2", "Group\\Section.one"],
            vec![
                "Open.onetoc2",
                "http\\host\\Open.onetoc2",
                "http\\host\\Section.one",
            ],
        ] {
            let bytes = cab(&names, b"data");
            let error = failure(&bytes);
            assert_eq!(error, Error::IncompleteNotebook);
        }
    }

    #[test]
    fn bounds_counts_before_cab_allocations() {
        for offset in [26, 28] {
            let mut bytes = cab(&["Open.onetoc2"], b"data");
            bytes[offset..offset + 2].copy_from_slice(&1025u16.to_le_bytes());
            let error = failure(&bytes);
            assert_eq!(error, Error::LimitExceeded);
        }
    }

    #[test]
    fn bounds_declared_member_size_and_actual_expansion_counter() {
        let mut bytes = cab(&["Open.onetoc2"], b"data");
        let files = u32::from_le_bytes(bytes[16..20].try_into().unwrap()) as usize;
        bytes[files..files + 4].copy_from_slice(&((MAX_MEMBER_BYTES + 1) as u32).to_le_bytes());
        let error = failure(&bytes);
        assert_eq!(error, Error::LimitExceeded);
        let mut actual = MAX_EXPANDED_BYTES - 1;
        let result = read_exact(&mut Cursor::new([1, 2]), &mut [0; 2], &mut actual);
        assert_eq!(result, Err(Error::LimitExceeded));
    }

    #[test]
    fn rejects_multipart_unsupported_compression_and_out_of_range_offsets() {
        let original = cab(&["Open.onetoc2"], b"data");
        let mut multipart = original.clone();
        multipart[30] = 1;
        let mut compression = original.clone();
        compression[42] = 2;
        let mut offset = original;
        offset[36..40].copy_from_slice(&u32::MAX.to_le_bytes());
        let multipart_result = failure(&multipart);
        let compression_result = failure(&compression);
        let offset_result = failure(&offset);
        assert_eq!(multipart_result, Error::UnsafePackage);
        assert_eq!(compression_result, Error::UnsupportedFile);
        assert_eq!(offset_result, Error::UnsafePackage);
    }

    #[test]
    fn rejects_overlapping_members_and_output_gaps_past_folder_end() {
        let original = cab(&["Open.onetoc2", "S.one"], b"data");
        let files = u32::from_le_bytes(original[16..20].try_into().unwrap()) as usize;
        let second = files + 16 + "Open.onetoc2".len() + 1;
        for invalid in [0u32, u32::MAX] {
            let mut bytes = original.clone();
            bytes[second + 4..second + 8].copy_from_slice(&invalid.to_le_bytes());
            let error = failure(&bytes);
            assert_eq!(error, Error::UnsafePackage);
        }
    }

    #[test]
    fn zero_block_folders_still_require_in_bounds_compressed_offsets() {
        let mut bytes = cab(&["Open.onetoc2"], b"data");
        let files = u32::from_le_bytes(bytes[16..20].try_into().unwrap()) as usize;
        bytes[36..40].copy_from_slice(&u32::MAX.to_le_bytes());
        bytes[40..42].copy_from_slice(&0u16.to_le_bytes());
        bytes[files..files + 4].copy_from_slice(&0u32.to_le_bytes());
        let error = failure(&bytes);
        assert_eq!(error, Error::UnsafePackage);
    }

    #[test]
    fn rejects_truncated_data_and_size_mismatches() {
        let mut bytes = cab(&["Open.onetoc2"], b"data");
        bytes.pop();
        let size = bytes.len() as u32;
        bytes[8..12].copy_from_slice(&size.to_le_bytes());
        let truncated = failure(&bytes);
        assert_eq!(truncated, Error::UnsafePackage);
        bytes.push(0);
        let size_mismatch = failure(&bytes);
        assert_eq!(size_mismatch, Error::UnsafePackage);
    }

    #[test]
    fn rejects_huge_unreferenced_folder_expansion_before_decompression() {
        let mut bytes = cab(&["Open.onetoc2"], b"data");
        let start = u32::from_le_bytes(bytes[36..40].try_into().unwrap()) as usize;
        let count = MAX_EXPANDED_BYTES / IO_CHUNK_BYTES + 1;
        bytes.truncate(start);
        bytes[40..42].copy_from_slice(&(count as u16).to_le_bytes());
        bytes[42..44].copy_from_slice(&1u16.to_le_bytes());
        for _ in 0..count {
            bytes.extend_from_slice(&0u32.to_le_bytes());
            bytes.extend_from_slice(&1u16.to_le_bytes());
            bytes.extend_from_slice(&(IO_CHUNK_BYTES as u16).to_le_bytes());
            bytes.push(0);
        }
        let size = bytes.len() as u32;
        bytes[8..12].copy_from_slice(&size.to_le_bytes());
        let error = failure(&bytes);
        assert_eq!(error, Error::LimitExceeded);
    }

    #[test]
    fn rejects_actual_checksum_corruption_and_truncated_compressed_streams() {
        let mut bytes = cab(&["Open.onetoc2"], b"data");
        let start = u32::from_le_bytes(bytes[36..40].try_into().unwrap()) as usize;
        bytes[start..start + 4].copy_from_slice(&1u32.to_le_bytes());
        let result = extract(&bytes);
        assert!(matches!(result, Err(Error::UnsafePackage)));
    }

    #[test]
    fn decodes_lzx_with_the_same_bounded_folder_reader() {
        // Public MIT-licensed cab 0.6.0 regression stream (src/cabinet.rs,
        // read_lzx_cabinet_with_two_files). The surrounding CAB is generated.
        let compressed = b"\x5b\x80\x80\x8d\x00\x30\xf0\x01\x10\x00\x00\x00\
            \x01\x00\x00\x00\x01\x00\x00\x00Hello, world!\r\nSee you later!\r\n\x00";
        let expected = b"Hello, world!\r\nSee you later!\r\n";
        let mut bytes = cab(&["Open.onetoc2"], expected);
        let start = u32::from_le_bytes(bytes[36..40].try_into().unwrap()) as usize;
        bytes.truncate(start);
        bytes[42..44].copy_from_slice(&0x1303u16.to_le_bytes());
        bytes.extend_from_slice(&0u32.to_le_bytes());
        bytes.extend_from_slice(&(compressed.len() as u16).to_le_bytes());
        bytes.extend_from_slice(&(expected.len() as u16).to_le_bytes());
        bytes.extend_from_slice(compressed);
        let size = bytes.len() as u32;
        bytes[8..12].copy_from_slice(&size.to_le_bytes());
        let plan = preflight(&bytes).unwrap();
        let mut cabinet = cab::Cabinet::new(FolderCab::new(&bytes, &plan, &[0])).unwrap();
        let mut output = vec![0; expected.len()];
        let mut actual = 0;
        let mut reader = cabinet.read_file("folder-0").unwrap();
        read_exact(&mut reader, &mut output, &mut actual).unwrap();
        assert_eq!(output, expected);
        assert_eq!(actual, expected.len());
    }

    #[test]
    fn only_selected_folder_payloads_are_exposed_to_cab() {
        let bytes = cab(&["Open.onetoc2", "asset.bin", "S.one"], b"data");
        let plan = preflight(&bytes).unwrap();
        let reader = FolderCab::new(&bytes, &plan, &[0]);
        let mut cabinet = cab::Cabinet::new(reader).unwrap();
        let mut stream = cabinet.read_file("folder-0").unwrap();
        let mut output = Vec::new();
        stream.read_to_end(&mut output).unwrap();
        assert_eq!(output, b"datadatadata");
    }
}
