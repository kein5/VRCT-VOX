//! A child that cannot outlive the thread that owns it.
//!
//! Linux: the kernel sends the child SIGKILL when the thread that started it ends, so a
//! crash of the app cannot leave a server holding the GPU. Windows: the child sits in a
//! kill-on-close job whose only handle this process holds.

use std::io;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::time::{Duration, Instant};

pub(crate) struct Owned {
    pub child: Child,
    #[cfg(windows)]
    pub job: windows::Job,
}

/// `command` with its error stream piped, started under this thread's ownership.
pub(crate) fn spawn(mut command: Command) -> io::Result<Owned> {
    command.stdout(Stdio::null()).stderr(Stdio::piped());
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::process::CommandExt;
        let parent = std::process::id() as libc::pid_t;
        // Runs in the child between fork and exec: only async-signal-safe calls.
        unsafe {
            command.pre_exec(move || {
                if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL as libc::c_ulong) != 0 {
                    return Err(io::Error::last_os_error());
                }
                // The owner may have died before prctl took effect.
                if libc::getppid() != parent {
                    return Err(io::Error::from_raw_os_error(libc::ESRCH));
                }
                Ok(())
            });
        }
    }
    #[cfg(windows)]
    {
        return windows::spawn(command);
    }
    #[cfg(not(windows))]
    Ok(Owned { child: command.spawn()? })
}

fn wait(child: &mut Child, timeout: Duration) -> io::Result<Option<ExitStatus>> {
    let deadline = Instant::now() + timeout;
    loop {
        if let Some(status) = child.try_wait()? {
            return Ok(Some(status));
        }
        if Instant::now() >= deadline {
            return Ok(None);
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

/// Ask the child to end, then end it. False when its end could not be confirmed.
pub(crate) fn end(child: &mut Child) -> bool {
    let mut ended = || -> io::Result<bool> {
        if child.try_wait()?.is_some() {
            return Ok(true);
        }
        #[cfg(unix)]
        unsafe {
            libc::kill(child.id() as libc::pid_t, libc::SIGTERM);
        }
        #[cfg(not(unix))]
        child.kill()?;
        if wait(child, Duration::from_secs(1))?.is_some() {
            return Ok(true);
        }
        child.kill()?;
        Ok(wait(child, Duration::from_millis(500))?.is_some())
    };
    ended().unwrap_or(false)
}

#[cfg(windows)]
mod windows {
    use std::io;
    use std::os::windows::io::AsRawHandle;
    use std::os::windows::process::CommandExt;
    use std::process::Command;

    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Threading::{
        ProcessPowerThrottling, SetProcessInformation, CREATE_NO_WINDOW, CREATE_SUSPENDED,
        PROCESS_POWER_THROTTLING_CURRENT_VERSION, PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
        PROCESS_POWER_THROTTLING_STATE,
    };

    #[link(name = "ntdll")]
    extern "system" {
        fn NtResumeProcess(process: HANDLE) -> i32;
    }

    /// A kill-on-close job object holding one child.
    pub(crate) struct Job(HANDLE);

    // The handle is only closed, once, by the thread that drops the job.
    unsafe impl Send for Job {}

    impl Drop for Job {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }

    impl Job {
        fn new() -> io::Result<Job> {
            let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
            if handle.is_null() {
                return Err(io::Error::last_os_error());
            }
            let job = Job(handle);
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let set = unsafe {
                SetInformationJobObject(
                    job.0,
                    JobObjectExtendedLimitInformation,
                    (&raw const limits).cast(),
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )
            };
            if set == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(job)
        }
    }

    /// Windows treats a process without a window as background work and keeps it on
    /// efficiency cores. Best effort: an older Windows runs the child without this hint.
    fn no_throttling(process: HANDLE) {
        let state = PROCESS_POWER_THROTTLING_STATE {
            Version: PROCESS_POWER_THROTTLING_CURRENT_VERSION,
            ControlMask: PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
            StateMask: 0,
        };
        unsafe {
            SetProcessInformation(
                process,
                ProcessPowerThrottling,
                (&raw const state).cast(),
                std::mem::size_of::<PROCESS_POWER_THROTTLING_STATE>() as u32,
            );
        }
    }

    /// Started suspended, so that it is in the job before it runs: it cannot escape.
    pub(crate) fn spawn(mut command: Command) -> io::Result<super::Owned> {
        let job = Job::new()?;
        command.creation_flags(CREATE_NO_WINDOW | CREATE_SUSPENDED);
        let mut child = command.spawn()?;
        let process = child.as_raw_handle() as HANDLE;
        let held = unsafe { AssignProcessToJobObject(job.0, process) } != 0;
        let failure = if held { None } else { Some(io::Error::last_os_error()) };
        if held {
            no_throttling(process);
        }
        if !held || unsafe { NtResumeProcess(process) } != 0 {
            let _ = child.kill();
            let _ = child.wait();
            return Err(failure.unwrap_or_else(|| io::Error::other("resume_failed")));
        }
        Ok(super::Owned { child, job })
    }
}
