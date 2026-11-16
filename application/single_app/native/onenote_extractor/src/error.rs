// error.rs

use serde::Serialize;

use crate::limits::PROTOCOL_VERSION;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Error {
    InvalidFile,
    UnsupportedFile,
    EncryptedFile,
    UnsafePackage,
    LimitExceeded,
    IncompleteNotebook,
    NoText,
    ExtractionFailed,
}

pub type Result<T> = std::result::Result<T, Error>;

impl Error {
    #[cfg(any(target_os = "linux", test))]
    pub(crate) fn from_response(bytes: &[u8]) -> Option<Self> {
        [
            Self::InvalidFile,
            Self::UnsupportedFile,
            Self::EncryptedFile,
            Self::UnsafePackage,
            Self::LimitExceeded,
            Self::IncompleteNotebook,
            Self::NoText,
            Self::ExtractionFailed,
        ]
        .into_iter()
        .find(|error| error.response() == bytes)
    }

    pub fn response(self) -> Vec<u8> {
        #[derive(Serialize)]
        struct Detail {
            code: Error,
        }
        #[derive(Serialize)]
        struct Response {
            protocol_version: u32,
            error: Detail,
        }
        serde_json::to_vec(&Response {
            protocol_version: PROTOCOL_VERSION,
            error: Detail { code: self },
        })
        .unwrap_or_else(|_| {
            b"{\"protocol_version\":1,\"error\":{\"code\":\"extraction_failed\"}}".to_vec()
        })
    }
}

pub(crate) fn parser_error(error: &onenote_parser::errors::Error) -> Error {
    // The pinned parser does not expose ErrorKind. Match only its fixed
    // encryption diagnostic; never expose or otherwise interpret its data.
    if error
        .to_string()
        .contains("This object may be encrypted or corrupt.")
    {
        Error::EncryptedFile
    } else {
        Error::InvalidFile
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use onenote_parser::errors::ErrorKind;

    #[test]
    fn encryption_diagnostic_is_classified_without_exposing_it() {
        let encrypted = ErrorKind::MalformedOneStoreData(
            "'odcs' is 0x1. This object may be encrypted or corrupt.".into(),
        )
        .into();
        let error = parser_error(&encrypted);
        assert_eq!(error, Error::EncryptedFile);
        assert_eq!(
            error.response(),
            b"{\"protocol_version\":1,\"error\":{\"code\":\"encrypted_file\"}}"
        );
    }

    #[test]
    fn failed_worker_output_must_be_an_exact_safe_error_response() {
        let valid = Error::from_response(&Error::LimitExceeded.response());
        let partial_success = Error::from_response(b"{\"protocol_version\":1,\"pages\":[");
        let extra_data = Error::from_response(
            b"{\"protocol_version\":1,\"error\":{\"code\":\"invalid_file\",\"detail\":\"private\"}}"
        );
        assert_eq!(valid, Some(Error::LimitExceeded));
        assert_eq!(partial_success, None);
        assert_eq!(extra_data, None);
    }
}
