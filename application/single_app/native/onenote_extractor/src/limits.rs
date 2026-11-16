// limits.rs

pub const PARSER_REVISION: &str = "d0d3330f9674f07903664329f50434d997eced8c";
pub const PROTOCOL_VERSION: u32 = 1;
pub const MAX_INPUT_BYTES: usize = 128 * 1024 * 1024;
pub const MAX_MEMBER_BYTES: usize = 128 * 1024 * 1024;
pub const MAX_EXPANDED_BYTES: usize = 256 * 1024 * 1024;
pub const MAX_MEMBERS: usize = 1024;
pub const MAX_CAB_BLOCKS: usize = 65_536;
pub const MAX_DEPTH: usize = 16;
pub const MAX_PAGES: usize = 10_000;
pub const MAX_TEXT_BYTES: usize = 16 * 1024 * 1024;
pub const MAX_OUTPUT_BYTES: usize = 32 * 1024 * 1024;
pub const MAX_TITLE_CHARS: usize = 4096;
pub const MAX_COMPONENT_CHARS: usize = 1024;
pub const MAX_MEMORY_BYTES: u64 = 1024 * 1024 * 1024;
pub const MAX_CPU_SECONDS: u64 = 120;
pub const IO_CHUNK_BYTES: usize = 32 * 1024;
