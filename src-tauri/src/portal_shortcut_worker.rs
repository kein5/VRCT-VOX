//! Portal lifecycle policy, independent of Tauri and D-Bus. The adapter owns
//! Request/Session cleanup; this worker owns admission, deadlines and retries.
use std::future::Future;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Condvar, Mutex};
use std::task::{Context, Poll, Wake, Waker};
use std::time::{Duration, Instant};

const CANCEL_POLL: Duration = Duration::from_millis(25);
const RETRY_MIN: Duration = Duration::from_millis(250);
const RETRY_MAX: Duration = Duration::from_secs(2);

#[derive(Clone)]
pub struct Operation {
    generation: u64,
    latest: Arc<AtomicU64>,
    cancelled: Arc<AtomicBool>,
    pub deadline: Instant,
}

impl Operation {
    pub fn check(&self) -> Result<(), String> {
        if Instant::now() >= self.deadline {
            Err("portal_timeout".into())
        } else if self.cancelled.load(Ordering::Acquire) || self.latest.load(Ordering::Acquire) != self.generation {
            Err("portal_cancelled".into())
        } else {
            Ok(())
        }
    }

    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    pub fn wait<F: Future>(&self, future: F) -> Result<F::Output, String> {
        wait_until(self.deadline, || self.check(), future)
    }
}

struct ThreadWake(std::thread::Thread);
impl Wake for ThreadWake {
    fn wake(self: Arc<Self>) { self.0.unpark(); }
    fn wake_by_ref(self: &Arc<Self>) { self.0.unpark(); }
}

/// Drive zbus's runtime-independent futures on the dedicated worker. Never
/// block in a D-Bus iterator: cancellation is checked even without a signal.
pub fn wait_until<F: Future>(deadline: Instant, check: impl Fn() -> Result<(), String>, future: F) -> Result<F::Output, String> {
    let waker = Waker::from(Arc::new(ThreadWake(std::thread::current())));
    let mut context = Context::from_waker(&waker);
    let mut future = std::pin::pin!(future);
    loop {
        check()?;
        if Instant::now() >= deadline { return Err("portal_timeout".into()); }
        if let Poll::Ready(value) = future.as_mut().poll(&mut context) {
            check()?;
            if Instant::now() >= deadline { return Err("portal_timeout".into()); }
            return Ok(value);
        }
        std::thread::park_timeout(CANCEL_POLL.min(deadline.saturating_duration_since(Instant::now())));
    }
}

pub struct Job<B, A> {
    pub binding: B,
    pub operation: Operation,
    reply: mpsc::Sender<Result<A, String>>,
}

/// Cancels on caller timeout or when the invoking task is dropped.
pub struct Ticket<A> {
    pub operation: Operation,
    result: mpsc::Receiver<Result<A, String>>,
}
impl<A> Ticket<A> {
    pub fn receive(&self) -> Result<A, String> {
        self.result.recv_timeout(self.operation.deadline.saturating_duration_since(Instant::now()))
            .map_err(|_| "portal_timeout".to_owned())?
    }
}
impl<A> Drop for Ticket<A> {
    fn drop(&mut self) { self.operation.cancel(); }
}

pub struct Mailbox<B, A> {
    latest: Arc<AtomicU64>,
    pending: Mutex<Option<Job<B, A>>>,
    ready: Condvar,
}
impl<B, A> Default for Mailbox<B, A> {
    fn default() -> Self {
        Self { latest: Arc::new(AtomicU64::new(0)), pending: Mutex::new(None), ready: Condvar::new() }
    }
}
impl<B, A> Mailbox<B, A> {
    pub fn submit(&self, binding: B, timeout: Duration) -> Ticket<A> {
        let (reply, result) = mpsc::channel();
        let mut pending = self.pending.lock().unwrap();
        let operation = Operation {
            generation: self.latest.fetch_add(1, Ordering::AcqRel) + 1,
            latest: self.latest.clone(), cancelled: Arc::new(AtomicBool::new(false)),
            deadline: Instant::now() + timeout,
        };
        if let Some(old) = pending.replace(Job { binding, operation: operation.clone(), reply }) {
            let _ = old.reply.send(Err("portal_cancelled".into()));
        }
        self.ready.notify_one();
        Ticket { operation, result }
    }

    pub fn next(&self) -> Job<B, A> {
        let mut pending = self.pending.lock().unwrap();
        loop {
            if let Some(job) = pending.take() { return job; }
            pending = self.ready.wait(pending).unwrap();
        }
    }
}

pub trait Backend {
    type Binding: Clone + Eq;
    type Assigned: Clone;
    fn alive(&self) -> bool;
    fn bind(&mut self, binding: &Self::Binding, operation: &Operation) -> Result<Self::Assigned, String>;
    /// Close the current request/session and retire the connection/listener.
    fn close(&mut self);
}

pub struct Worker<P: Backend> {
    portal: Option<P>,
    bound: Option<(P::Binding, P::Assigned)>,
    retry: Option<(Instant, String)>,
    backoff: Duration,
}
impl<P: Backend> Default for Worker<P> {
    fn default() -> Self {
        Self { portal: None, bound: None, retry: None, backoff: RETRY_MIN }
    }
}
impl<P: Backend> Worker<P> {
    fn invalidate(&mut self) {
        self.bound = None;
        if let Some(mut portal) = self.portal.take() { portal.close(); }
    }

    pub fn process(&mut self, job: Job<P::Binding, P::Assigned>, open: impl FnOnce(&Operation) -> Result<P, String>) {
        let result = self.bind(&job.binding, &job.operation, open);
        // Admission can change even after the adapter returns success.
        let result = match job.operation.check() {
            Ok(()) => result,
            Err(code) => { self.invalidate(); Err(code) }
        };
        let _ = job.reply.send(result);
    }

    fn bind(&mut self, binding: &P::Binding, operation: &Operation, open: impl FnOnce(&Operation) -> Result<P, String>) -> Result<P::Assigned, String> {
        operation.check()?;
        if self.portal.as_ref().is_some_and(|portal| !portal.alive()) { self.invalidate(); }
        if self.portal.is_none() {
            if let Some((until, code)) = &self.retry {
                if Instant::now() < *until { return Err(code.clone()); }
            }
            match open(operation) {
                Ok(portal) => {
                    self.portal = Some(portal);
                    self.retry = None;
                    self.backoff = RETRY_MIN;
                }
                Err(code) => {
                    // A later deliberate bind may reconnect; never retry on a timer.
                    if operation.check().is_ok() {
                        self.retry = Some((Instant::now() + self.backoff, code.clone()));
                        self.backoff = (self.backoff * 2).min(RETRY_MAX);
                    }
                    return Err(code);
                }
            }
        }
        operation.check()?;
        if let Some((previous, assigned)) = &self.bound {
            if previous == binding { return Ok(assigned.clone()); }
        }
        self.bound = None;
        let result = self.portal.as_mut().unwrap().bind(binding, operation);
        operation.check()?;
        match result {
            Ok(assigned) if self.portal.as_ref().unwrap().alive() => {
                self.bound = Some((binding.clone(), assigned.clone()));
                Ok(assigned)
            }
            result => {
                self.invalidate();
                result.and(Err("portal_unavailable".into()))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::future::poll_fn;
    use std::sync::atomic::AtomicUsize;

    #[derive(Default)]
    struct FakeState {
        opens: AtomicUsize,
        binds: AtomicUsize,
        applied: AtomicUsize,
        closed_requests: AtomicUsize,
        closed_sessions: AtomicUsize,
        alive: AtomicBool,
    }
    enum Response { Ready, Pending, Cancel, Expire, Supersede }
    struct FakePortal {
        state: Arc<FakeState>,
        response: Response,
        request: bool,
        session: bool,
    }
    impl FakePortal {
        fn open(state: &Arc<FakeState>, response: Response) -> Self {
            state.opens.fetch_add(1, Ordering::Relaxed);
            state.alive.store(true, Ordering::Release);
            Self { state: state.clone(), response, request: false, session: false }
        }
    }
    impl Backend for FakePortal {
        type Binding = u32;
        type Assigned = u32;
        fn alive(&self) -> bool { self.state.alive.load(Ordering::Acquire) }
        fn bind(&mut self, binding: &u32, operation: &Operation) -> Result<u32, String> {
            self.state.binds.fetch_add(1, Ordering::Relaxed);
            self.request = true;
            self.session = true;
            match self.response {
                Response::Ready => operation.wait(std::future::ready(()))?,
                Response::Pending => operation.wait(std::future::pending::<()>())?,
                Response::Cancel => operation.wait(poll_fn(|_| {
                    operation.cancel();
                    Poll::Ready(())
                }))?,
                Response::Expire => operation.wait(poll_fn(|_| {
                    std::thread::sleep(operation.deadline.saturating_duration_since(Instant::now()));
                    Poll::Ready(())
                }))?,
                Response::Supersede => operation.wait(poll_fn(|_| {
                    operation.latest.fetch_add(1, Ordering::AcqRel);
                    Poll::Ready(())
                }))?,
            }
            // Mirrors the adapter's mutation boundary after the portal response.
            operation.check()?;
            self.request = false;
            self.state.applied.fetch_add(1, Ordering::Relaxed);
            Ok(*binding)
        }
        fn close(&mut self) {
            if self.request { self.state.closed_requests.fetch_add(1, Ordering::Relaxed); }
            if self.session { self.state.closed_sessions.fetch_add(1, Ordering::Relaxed); }
            self.request = false;
            self.session = false;
        }
    }

    fn abandoned(response: Response, expected: &str) {
        let jobs = Mailbox::default();
        let ticket = jobs.submit(1, Duration::from_millis(20));
        let state = Arc::new(FakeState::default());
        let mut worker = Worker::default();
        let job = jobs.next();
        worker.process(job, |_| Ok(FakePortal::open(&state, response)));
        // Inspect the delivered result directly: the caller deadline has elapsed.
        assert_eq!(ticket.result.try_recv().unwrap(), Err(expected.into()));
        assert_eq!(state.closed_requests.load(Ordering::Relaxed), 1);
        assert_eq!(state.closed_sessions.load(Ordering::Relaxed), 1);
        assert_eq!(state.applied.load(Ordering::Relaxed), 0);
        assert!(worker.bound.is_none());
        assert!(worker.portal.is_none());
    }

    #[test]
    fn deadline_closes_unanswered_request_and_session() { abandoned(Response::Pending, "portal_timeout"); }
    #[test]
    fn caller_cancellation_closes_request_and_session() { abandoned(Response::Cancel, "portal_cancelled"); }
    #[test]
    fn response_arriving_at_deadline_cannot_apply_binding() { abandoned(Response::Expire, "portal_timeout"); }
    #[test]
    fn superseded_response_cannot_apply_binding() { abandoned(Response::Supersede, "portal_cancelled"); }

    #[test]
    fn mailbox_keeps_only_newest_pending_job_and_cancels_active_generation() {
        let jobs = Mailbox::<u32, u32>::default();
        let active = jobs.submit(1, Duration::from_secs(1));
        let job = jobs.next();
        let second = jobs.submit(2, Duration::from_secs(1));
        let third = jobs.submit(3, Duration::from_secs(1));
        assert_eq!(second.receive(), Err("portal_cancelled".into()));
        assert_eq!(job.operation.check(), Err("portal_cancelled".into()));
        assert_eq!(jobs.next().binding, 3);
        assert!(jobs.pending.lock().unwrap().is_none());
        drop((active, third));
    }

    #[test]
    fn expired_pending_job_does_not_open_portal() {
        let jobs = Mailbox::<u32, u32>::default();
        let ticket = jobs.submit(1, Duration::ZERO);
        let mut worker = Worker::<FakePortal>::default();
        worker.process(jobs.next(), |_| panic!("expired generation must not open"));
        assert_eq!(ticket.result.try_recv().unwrap(), Err("portal_timeout".into()));
    }

    #[test]
    fn dropping_caller_cancels_its_operation() {
        let jobs = Mailbox::<u32, u32>::default();
        let ticket = jobs.submit(1, Duration::from_secs(1));
        let job = jobs.next();
        drop(ticket);
        assert_eq!(job.operation.check(), Err("portal_cancelled".into()));
    }

    #[test]
    fn failed_open_resets_and_deliberate_retry_reconnects_after_bounded_backoff() {
        let jobs = Mailbox::<u32, u32>::default();
        let state = Arc::new(FakeState::default());
        let mut worker = Worker::default();
        for _ in 0..6 {
            let ticket = jobs.submit(1, Duration::from_secs(1));
            worker.process(jobs.next(), |_| {
                state.opens.fetch_add(1, Ordering::Relaxed);
                Err::<FakePortal, _>("portal_unavailable".into())
            });
            assert_eq!(ticket.receive(), Err("portal_unavailable".into()));
            assert!(worker.portal.is_none());
            assert!(worker.backoff <= RETRY_MAX);
            let quick_retry = jobs.submit(1, Duration::from_secs(1));
            worker.process(jobs.next(), |_| panic!("cooldown must not reopen"));
            assert_eq!(quick_retry.receive(), Err("portal_unavailable".into()));
            // Move the clock boundary without a real retry timer or long sleep.
            worker.retry.as_mut().unwrap().0 = Instant::now();
        }
        assert_eq!(state.opens.load(Ordering::Relaxed), 6);
        let retry = jobs.submit(1, Duration::from_secs(1));
        worker.process(jobs.next(), |_| Ok(FakePortal::open(&state, Response::Ready)));
        assert_eq!(retry.receive(), Ok(1));
        assert_eq!(state.opens.load(Ordering::Relaxed), 7);
        assert!(worker.retry.is_none());
        assert_eq!(worker.backoff, RETRY_MIN);
    }

    #[test]
    fn closed_session_or_lost_connection_invalidates_cached_binding() {
        let jobs = Mailbox::default();
        let state = Arc::new(FakeState::default());
        let mut worker = Worker::default();
        for (index, expected_binds) in [1, 1, 2].into_iter().enumerate() {
            let ticket = jobs.submit(42, Duration::from_secs(1));
            worker.process(jobs.next(), |_| Ok(FakePortal::open(&state, Response::Ready)));
            assert_eq!(ticket.receive(), Ok(42));
            assert_eq!(state.binds.load(Ordering::Relaxed), expected_binds);
            if index == 1 { state.alive.store(false, Ordering::Release); }
        }
        assert_eq!(state.opens.load(Ordering::Relaxed), 2);
        assert_eq!(state.closed_sessions.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn worker_rejects_success_returned_by_adapter_after_cancellation() {
        struct LatePortal;
        impl Backend for LatePortal {
            type Binding = u32;
            type Assigned = u32;
            fn alive(&self) -> bool { true }
            fn bind(&mut self, binding: &u32, operation: &Operation) -> Result<u32, String> {
                operation.cancel();
                Ok(*binding)
            }
            fn close(&mut self) {}
        }
        let jobs = Mailbox::default();
        let ticket = jobs.submit(1, Duration::from_secs(1));
        let mut worker = Worker::default();
        worker.process(jobs.next(), |_| Ok(LatePortal));
        assert_eq!(ticket.receive(), Err("portal_cancelled".into()));
        assert!(worker.bound.is_none());
    }
}
