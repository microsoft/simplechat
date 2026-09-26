// runtime.rs

use crate::error::{Error, Result};
use crate::limits::{MAX_CPU_SECONDS, MAX_MEMORY_BYTES};

pub struct Response {
    pub bytes: Vec<u8>,
    pub code: u8,
}

impl Response {
    pub fn error(error: Error) -> Self {
        Self {
            bytes: error.response(),
            code: 2,
        }
    }
}

fn evaluate(work: impl FnOnce() -> Result<Vec<u8>>) -> Response {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(work)) {
        Ok(Ok(bytes)) => Response { bytes, code: 0 },
        Ok(Err(error)) => Response::error(error),
        Err(_) => Response::error(Error::ExtractionFailed),
    }
}

#[cfg(target_os = "linux")]
mod platform {
    use std::fs::File;
    use std::io::{Read, Write};
    use std::os::fd::FromRawFd;

    use super::*;
    use crate::limits::{IO_CHUNK_BYTES, MAX_OUTPUT_BYTES};

    pub struct Guard;

    fn limit(resource: libc::__rlimit_resource_t, requested: u64) -> Result<()> {
        let mut current = libc::rlimit {
            rlim_cur: 0,
            rlim_max: 0,
        };
        // SAFETY: current is valid writable storage and resource is an RLIMIT_* constant.
        if unsafe { libc::getrlimit(resource, &mut current) } != 0 {
            return Err(Error::ExtractionFailed);
        }
        let value = libc::rlimit {
            rlim_cur: current.rlim_cur.min(requested),
            rlim_max: current.rlim_max.min(requested),
        };
        // SAFETY: value is a correctly initialized rlimit for this process.
        if unsafe { libc::setrlimit(resource, &value) } != 0 {
            return Err(Error::ExtractionFailed);
        }
        Ok(())
    }

    pub fn apply() -> Result<Guard> {
        limit(libc::RLIMIT_CORE, 0)?;
        limit(libc::RLIMIT_AS, MAX_MEMORY_BYTES)?;
        limit(libc::RLIMIT_CPU, MAX_CPU_SECONDS)?;
        // SAFETY: reset only this single-threaded executable's child disposition.
        // An inherited SIG_IGN would auto-reap the worker before waitpid.
        if unsafe { libc::signal(libc::SIGCHLD, libc::SIG_DFL) } == libc::SIG_ERR {
            return Err(Error::ExtractionFailed);
        }
        // SAFETY: these prctl operations take scalar arguments and affect only this process.
        let hardened = unsafe {
            libc::prctl(libc::PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
                && libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0
        };
        if !hardened {
            return Err(Error::ExtractionFailed);
        }
        Ok(Guard)
    }

    fn wait(pid: libc::pid_t) -> Result<i32> {
        loop {
            let mut status = 0;
            // SAFETY: pid is the child owned by this supervisor; status is writable.
            let waited = unsafe { libc::waitpid(pid, &mut status, 0) };
            if waited == pid {
                return Ok(status);
            }
            if std::io::Error::last_os_error().kind() != std::io::ErrorKind::Interrupted {
                return Err(Error::ExtractionFailed);
            }
        }
    }

    fn silence() -> Result<()> {
        // SAFETY: the static C string is NUL terminated and flags are valid.
        let null = unsafe { libc::open(c"/dev/null".as_ptr(), libc::O_WRONLY | libc::O_CLOEXEC) };
        if null < 0 {
            return Err(Error::ExtractionFailed);
        }
        // SAFETY: null is an owned descriptor; stdout/stderr are replaced only in the child.
        let success = unsafe {
            let success = libc::dup2(null, libc::STDOUT_FILENO) >= 0
                && libc::dup2(null, libc::STDERR_FILENO) >= 0;
            if null > libc::STDERR_FILENO {
                libc::close(null);
            }
            success
        };
        if success {
            Ok(())
        } else {
            Err(Error::ExtractionFailed)
        }
    }

    pub fn execute(work: impl FnOnce() -> Result<Vec<u8>>) -> Response {
        let mut descriptors = [-1; 2];
        // SAFETY: descriptors has space for the two descriptors written by pipe2.
        if unsafe { libc::pipe2(descriptors.as_mut_ptr(), libc::O_CLOEXEC) } != 0 {
            return Response::error(Error::ExtractionFailed);
        }
        // SAFETY: this executable calls execute before starting any threads.
        let parent = unsafe { libc::getpid() };
        // SAFETY: the executable is single-threaded here, with no inherited Python state.
        let pid = unsafe { libc::fork() };
        if pid < 0 {
            // SAFETY: these descriptors were just returned by pipe2 and are owned here.
            unsafe {
                libc::close(descriptors[0]);
                libc::close(descriptors[1]);
            }
            return Response::error(Error::ExtractionFailed);
        }
        if pid == 0 {
            // SAFETY: close only the child's unused pipe end. Scalar prctl installs
            // termination when the supervisor dies, including a Python wall timeout.
            let parent_alive = unsafe {
                libc::close(descriptors[0]);
                libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0) == 0
                    && libc::getppid() == parent
            };
            let response = if parent_alive {
                match silence() {
                    Ok(()) => evaluate(work),
                    Err(error) => Response::error(error),
                }
            } else {
                Response::error(Error::ExtractionFailed)
            };
            // SAFETY: this child owns the write descriptor and gives it to File exactly once.
            let mut channel = unsafe { File::from_raw_fd(descriptors[1]) };
            let written = channel.write_all(&response.bytes).is_ok();
            let code = if written { response.code as i32 } else { 2 };
            // SAFETY: do not run parent process destructors after fork.
            unsafe { libc::_exit(code) }
        }
        // SAFETY: the parent owns its read end; the write end belongs only to the child.
        let mut channel = unsafe {
            libc::close(descriptors[1]);
            File::from_raw_fd(descriptors[0])
        };
        let mut bytes = Vec::new();
        let mut chunk = [0; IO_CHUNK_BYTES];
        let mut failure = None;
        loop {
            match channel.read(&mut chunk) {
                Ok(0) => break,
                Ok(size) => {
                    if size > MAX_OUTPUT_BYTES - bytes.len() {
                        failure = Some(Error::LimitExceeded);
                        break;
                    }
                    bytes.extend_from_slice(&chunk[..size]);
                }
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => {}
                Err(_) => {
                    failure = Some(Error::ExtractionFailed);
                    break;
                }
            }
        }
        if failure.is_some() {
            // SAFETY: pid is the still-owned worker, never an arbitrary system process.
            unsafe {
                libc::kill(pid, libc::SIGKILL);
            }
        }
        let status = match wait(pid) {
            Ok(status) => status,
            Err(error) => return Response::error(error),
        };
        if let Some(error) = failure {
            return Response::error(error);
        }
        if libc::WIFSIGNALED(status) {
            return Response::error(match libc::WTERMSIG(status) {
                libc::SIGXCPU | libc::SIGKILL | libc::SIGABRT | libc::SIGSEGV => {
                    Error::LimitExceeded
                }
                _ => Error::ExtractionFailed,
            });
        }
        let code = libc::WEXITSTATUS(status);
        if !libc::WIFEXITED(status) || !matches!(code, 0 | 2) || bytes.is_empty() {
            return Response::error(Error::ExtractionFailed);
        }
        if code == 2 {
            return Response::error(
                Error::from_response(&bytes).unwrap_or(Error::ExtractionFailed),
            );
        }
        Response {
            bytes,
            code: code as u8,
        }
    }
}

#[cfg(windows)]
mod platform {
    use std::ptr;

    use super::*;
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE, INVALID_HANDLE_VALUE};
    use windows_sys::Win32::Storage::FileSystem::{
        CreateFileW, FILE_ATTRIBUTE_NORMAL, FILE_GENERIC_WRITE, FILE_SHARE_READ, FILE_SHARE_WRITE,
        OPEN_EXISTING,
    };
    use windows_sys::Win32::System::Console::{
        GetStdHandle, STD_ERROR_HANDLE, STD_OUTPUT_HANDLE, SetStdHandle,
    };
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION,
        JOB_OBJECT_LIMIT_PROCESS_MEMORY, JOB_OBJECT_LIMIT_PROCESS_TIME,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
        SetInformationJobObject,
    };
    use windows_sys::Win32::System::Threading::GetCurrentProcess;

    pub struct Guard(HANDLE);

    impl Drop for Guard {
        fn drop(&mut self) {
            // SAFETY: Guard owns this valid job handle.
            unsafe {
                CloseHandle(self.0);
            }
        }
    }

    pub fn apply() -> Result<Guard> {
        // SAFETY: null pointers request default security and an unnamed job.
        let job = unsafe { CreateJobObjectW(ptr::null(), ptr::null()) };
        if job.is_null() {
            return Err(Error::ExtractionFailed);
        }
        let guard = Guard(job);
        // SAFETY: a zeroed structure is a valid starting state for the documented job settings.
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | JOB_OBJECT_LIMIT_PROCESS_TIME
            | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION;
        info.BasicLimitInformation.PerProcessUserTimeLimit = (MAX_CPU_SECONDS * 10_000_000) as i64;
        info.ProcessMemoryLimit = MAX_MEMORY_BYTES as usize;
        // SAFETY: info has the exact structure and length required by the information class.
        let applied = unsafe {
            SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const _,
                std::mem::size_of_val(&info) as u32,
            ) != 0
                && AssignProcessToJobObject(job, GetCurrentProcess()) != 0
        };
        if applied {
            Ok(guard)
        } else {
            Err(Error::ExtractionFailed)
        }
    }

    pub fn execute(work: impl FnOnce() -> Result<Vec<u8>>) -> Response {
        // SAFETY: valid NUL-terminated device name, default security, no file creation.
        let null = unsafe {
            CreateFileW(
                [b'N' as u16, b'U' as u16, b'L' as u16, 0].as_ptr(),
                FILE_GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                ptr::null(),
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                ptr::null_mut(),
            )
        };
        if null == INVALID_HANDLE_VALUE {
            return Response::error(Error::ExtractionFailed);
        }
        // SAFETY: these are standard handle slots; replacements use the owned NUL handle.
        let (stdout, stderr, silenced) = unsafe {
            let stdout = GetStdHandle(STD_OUTPUT_HANDLE);
            let stderr = GetStdHandle(STD_ERROR_HANDLE);
            let success = SetStdHandle(STD_OUTPUT_HANDLE, null) != 0
                && SetStdHandle(STD_ERROR_HANDLE, null) != 0;
            (stdout, stderr, success)
        };
        let result = if silenced {
            evaluate(work)
        } else {
            Response::error(Error::ExtractionFailed)
        };
        // SAFETY: restore the exact original handles before closing the temporary NUL handle.
        unsafe {
            SetStdHandle(STD_OUTPUT_HANDLE, stdout);
            SetStdHandle(STD_ERROR_HANDLE, stderr);
            CloseHandle(null);
        }
        result
    }
}

#[cfg(not(any(target_os = "linux", windows)))]
mod platform {
    use super::*;
    pub struct Guard;
    pub fn apply() -> Result<Guard> {
        Err(Error::ExtractionFailed)
    }
    pub fn execute(_work: impl FnOnce() -> Result<Vec<u8>>) -> Response {
        Response::error(Error::ExtractionFailed)
    }
}

pub use platform::{apply, execute};
