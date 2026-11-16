// signature.rs

use crate::error::{Error, Result};

const SECTION: [u8; 16] = [
    0xe4, 0x52, 0x5c, 0x7b, 0x8c, 0xd8, 0xa7, 0x4d, 0xae, 0xb1, 0x53, 0x78, 0xd0, 0x29, 0x96, 0xd3,
];
const TOC: [u8; 16] = [
    0xa1, 0x2f, 0xff, 0x43, 0xd9, 0xef, 0x76, 0x4c, 0x9e, 0xe2, 0x10, 0xea, 0x57, 0x22, 0x76, 0x5f,
];
const DESKTOP: [u8; 16] = [
    0x3f, 0xdd, 0x9a, 0x10, 0x1b, 0x91, 0xf5, 0x49, 0xa5, 0xd0, 0x17, 0x91, 0xed, 0xc8, 0xae, 0xd8,
];
const FSSHTTP: [u8; 16] = [
    0x2f, 0xe9, 0x8d, 0x63, 0xd4, 0xa6, 0xc1, 0x4b, 0x9a, 0x36, 0xb3, 0xfc, 0x25, 0x11, 0xa5, 0xb7,
];

pub(crate) fn validate(data: &[u8], toc: bool) -> Result<()> {
    if data.len() < 64 || (data[..16] != SECTION && !(toc && data[..16] == TOC)) {
        return Err(Error::InvalidFile);
    }
    if data[48..64] != DESKTOP && data[48..64] != FSSHTTP {
        return Err(Error::UnsupportedFile);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn refuses_wrong_signatures_and_legacy_formats() {
        let zip = validate(b"PK\x03\x04", false);
        let short = validate(&SECTION, false);
        assert_eq!(zip, Err(Error::InvalidFile));
        assert_eq!(short, Err(Error::InvalidFile));
        let mut header = [0u8; 64];
        header[..16].copy_from_slice(&SECTION);
        let legacy = validate(&header, false);
        assert_eq!(legacy, Err(Error::UnsupportedFile));
        header[48..64].copy_from_slice(&DESKTOP);
        let section = validate(&header, false);
        // FSSHTTP packaging uses the section GUID even for a TOC. The parser
        // subsequently verifies the store's actual TableOfContents type.
        let packaged_toc = validate(&header, true);
        assert_eq!(section, Ok(()));
        assert_eq!(packaged_toc, Ok(()));
        header[..16].copy_from_slice(&TOC);
        let wrong_type = validate(&header, false);
        assert_eq!(wrong_type, Err(Error::InvalidFile));
    }
}
