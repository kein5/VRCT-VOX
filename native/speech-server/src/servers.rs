//! The three servers of the app, one per profile, with the generations that keep a late
//! Stop or a late end from acting on a newer start.

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use crate::server::{Health, Hooks, Launch, SpeechServer, State};
use crate::settings::{Profile, StartOptions};
use crate::{codes, Code};

/// A profile's state, with the generation a start has to name.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProfileState {
    pub health: Health,
    pub generation: u64,
}

struct Slot {
    owner: Option<(u64, Arc<SpeechServer>)>,
    generation: u64,
    /// Unlike the public generation, a run does not change on Stop or end.
    run: Option<u64>,
}

struct Shared {
    closed: bool,
    slots: [Slot; 3],
    next_owner: u64,
}

type EndHook = Box<dyn Fn(Profile, u64) + Send + Sync>;
type ServerHooks = Box<dyn Fn(Profile) -> Hooks + Send + Sync>;

struct Inner {
    launch: Launch,
    shared: Mutex<Shared>,
    on_end: Option<EndHook>,
    hooks: Option<ServerHooks>,
}

pub struct SpeechServers {
    inner: Arc<Inner>,
}

impl SpeechServers {
    /// `on_end(profile, run)` is told once when the server of that run ended by itself.
    pub fn new(launch: Launch, on_end: Option<EndHook>) -> SpeechServers {
        SpeechServers::with_hooks(launch, on_end, None)
    }

    /// `hooks(profile)` gives each new server its failure, listener and device hooks; its
    /// `on_end` is replaced by this owner's.
    pub fn with_hooks(launch: Launch, on_end: Option<EndHook>, hooks: Option<ServerHooks>) -> SpeechServers {
        let slot = || Slot { owner: None, generation: 0, run: None };
        let shared = Shared { closed: false, slots: [slot(), slot(), slot()], next_owner: 0 };
        SpeechServers { inner: Arc::new(Inner { launch, shared: Mutex::new(shared), on_end, hooks }) }
    }

    pub fn state(&self) -> [(Profile, ProfileState); 3] {
        let shared = self.inner.shared.lock().unwrap();
        Profile::ALL.map(|profile| {
            let slot = &shared.slots[profile.index()];
            let health = slot.owner.as_ref().map_or_else(Health::stopped, |(_, owner)| owner.health());
            (profile, ProfileState { health, generation: slot.generation })
        })
    }

    /// The address of a ready server.
    pub fn binding(&self, profile: Profile) -> Result<String, Code> {
        let shared = self.inner.shared.lock().unwrap();
        let health = shared.slots[profile.index()].owner.as_ref().map(|(_, owner)| owner.health());
        match health {
            Some(Health { state: State::Ready, base_url: Some(url), .. }) if !shared.closed => Ok(url),
            _ => Err(codes::NOT_READY),
        }
    }

    pub fn current_run(&self, profile: Profile) -> Option<u64> {
        self.inner.shared.lock().unwrap().slots[profile.index()].run
    }

    /// Start `profile`. `expected_generation` is the one `state` showed the caller: a
    /// start decided on an older state is refused.
    pub fn start(&self, profile: Profile, options: StartOptions, expected_generation: u64) -> Result<(), Code> {
        let mut shared = self.inner.shared.lock().unwrap();
        if shared.closed {
            return Err(codes::CLOSED);
        }
        if expected_generation != shared.slots[profile.index()].generation {
            return Err(codes::STALE_START);
        }
        if let Some((_, old)) = &shared.slots[profile.index()].owner {
            if matches!(old.health().state, State::Ready | State::Preparing) || !old.close(Duration::ZERO) {
                return Err(codes::BUSY);
            }
        }
        let run = shared.slots[profile.index()].generation + 1;
        let id = shared.next_owner;
        shared.next_owner += 1;
        let mut hooks = self.inner.hooks.as_ref().map_or_else(Hooks::default, |hooks| hooks(profile));
        let inner = Arc::downgrade(&self.inner);
        let notified = std::sync::atomic::AtomicBool::new(false);
        hooks.on_end = Some(Box::new(move |profile| {
            let Some(inner) = inner.upgrade() else { return };
            {
                let mut shared = inner.shared.lock().unwrap();
                let slot = &mut shared.slots[profile.index()];
                // An end is told once, and only while this server is still the profile's.
                if slot.owner.as_ref().map(|(owner, _)| *owner) != Some(id)
                    || notified.swap(true, std::sync::atomic::Ordering::SeqCst)
                {
                    return;
                }
                slot.generation += 1;
            }
            if let Some(on_end) = &inner.on_end {
                on_end(profile, run);
            }
        }));
        let owner = Arc::new(SpeechServer::new(profile, options, self.inner.launch.clone(), hooks));
        let slot = &mut shared.slots[profile.index()];
        slot.owner = Some((id, owner.clone()));
        slot.generation += 1;
        slot.run = Some(run);
        owner.start()
    }

    /// Stop `profile`. With a generation, stop only that exact start: a caller that owns
    /// one run must not stop a newer server the user started after it ended. `on_stop`
    /// is told the run that was stopped.
    pub fn stop(
        &self,
        profile: Profile,
        generation: Option<u64>,
        on_stop: Option<&dyn Fn(Profile, Option<u64>)>,
    ) -> bool {
        let run = {
            let mut shared = self.inner.shared.lock().unwrap();
            let slot = &mut shared.slots[profile.index()];
            if generation.is_some_and(|generation| generation != slot.generation) {
                return false;
            }
            slot.generation += 1;
            if let Some((_, owner)) = &slot.owner {
                owner.stop();
            }
            slot.run
        };
        // The stopped run is carried across the unlocked notification; a new Start or a
        // late child cleanup must not turn this into another run's end.
        if let Some(on_stop) = on_stop {
            on_stop(profile, run);
        }
        true
    }

    /// Stop every server and refuse new starts. True when every child is known to be gone.
    pub fn close(&self, timeout: Duration) -> bool {
        let deadline = Instant::now() + timeout;
        let owners: Vec<Arc<SpeechServer>> = {
            let mut shared = self.inner.shared.lock().unwrap();
            shared.closed = true;
            for slot in &mut shared.slots {
                slot.generation += 1;
            }
            shared.slots.iter().filter_map(|slot| slot.owner.as_ref().map(|(_, owner)| owner.clone())).collect()
        };
        for owner in &owners {
            owner.stop();
        }
        // Every owner is closed, also after one of them could not be confirmed.
        let mut confirmed = true;
        for owner in &owners {
            confirmed &= owner.close(deadline.saturating_duration_since(Instant::now()));
        }
        confirmed
    }
}
