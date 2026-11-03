import { isSidecarWarning } from "./sidecarDiagnostics.js";

// Kept on the shared UI store, not a component ref. Mounts attach to this owner;
// only a deliberate retry of a failed start can replace its session.
export const createSidecarSessionOwner = ({ store, createCommand, setInterval, clearInterval }) => {
    const clients = new Set();
    let lastClient;
    const handlers = () => (Array.from(clients).at(-1) ?? lastClient)?.();
    const isCurrent = session => store.backend_session === session;
    const isLive = session => isCurrent(session) && ["starting", "running"].includes(session.phase);
    const stopFeeding = session => {
        if (session.timer !== null) clearInterval(session.timer);
        session.timer = null;
    };
    const startFeeding = session => {
        if (!isLive(session) || !session.child || !clients.size || session.timer !== null) return;
        session.timer = setInterval(() => {
            if (isLive(session) && clients.size) handlers()?.feedWatchdog();
        }, 20000);
    };
    const retireChild = async session => {
        if (!session.child || session.closed) return true;
        if (!session.retirement) {
            session.retirement = Promise.resolve().then(() => session.child.kill()).then(() => true, error => {
                console.error("Could not stop failed sidecar attempt", error);
                return false;
            });
        }
        return await session.retirement;
    };
    const finish = (session, phase) => {
        if (!isLive(session)) return false;
        session.phase = phase;
        session.expectedExits.clear();
        stopFeeding(session);
        store.backend_subprocess = null;
        store.backend_stopped = true;
        handlers()?.backendStopped();
        handlers()?.setStartupState(phase);
        return true;
    };
    const fail = (session, error) => {
        if (!finish(session, "failed")) return;
        console.error("Sidecar startup failed", error);
        // If spawn is still pending, its completion retires the late child.
        if (session.child) void retireChild(session);
    };
    const start = () => {
        const session = { phase: "starting", child: null, timer: null, expectedExits: new Map(), retrying: false };
        store.backend_session = session;
        store.backend_subprocess = null;
        store.backend_stopped = false;
        handlers()?.beginStartup();
        handlers()?.setStartupState("starting");
        session.completion = Promise.resolve().then(async () => {
            try {
                const command = createCommand();
                // The shell plugin also reports stdout/stderr read errors here,
                // which do not stop the child. Only fail a start that has no child.
                command.on("error", error => {
                    if (session.phase === "starting" && !session.child) fail(session, error);
                    else if (isCurrent(session)) console.error("sidecar command error", error);
                });
                command.on("close", ({ code, signal } = {}) => {
                    if (!isCurrent(session)) return;
                    session.closed = true;
                    if (session.phase === "starting") {
                        fail(session, { code, signal });
                        return;
                    }
                    const expected = session.expectedExits.size > 0;
                    if (finish(session, "stopped") && !expected) handlers()?.unexpectedExit({ code, signal });
                });
                command.stdout.on("data", line => {
                    if (!isLive(session)) return;
                    // The shell plugin uses line mode; Windows CRLF can deliver
                    // an empty line. Escaped newlines inside JSON remain intact.
                    if (typeof line === "string" && line.trim() === "") return;
                    try {
                        handlers()?.receiveRoutes(JSON.parse(line));
                    } catch (error) {
                        console.log(error, line);
                    }
                });
                command.stderr.on("data", line => {
                    if (!isLive(session)) return;
                    if (isSidecarWarning(line)) console.warn("stderr (warning, ignored)", line);
                    else handlers()?.stderr(line);
                });
                const child = await command.spawn();
                session.child = child;
                if (!isLive(session)) {
                    await retireChild(session);
                    return;
                }
                store.backend_subprocess = child;
                session.phase = "running";
                handlers()?.setStartupState("running");
                startFeeding(session);
                if (clients.size) handlers()?.started(() => isLive(session) && clients.size > 0);
            } catch (error) {
                fail(session, error);
            }
        });
        return session;
    };
    const retry = async () => {
        const session = store.backend_session;
        if (!session || session.phase !== "failed" || session.retrying || !clients.size) return false;
        session.retrying = true;
        handlers()?.setStartupState("starting");
        // Do not spawn a replacement while an old spawn or kill is unresolved.
        await session.completion;
        const retired = await retireChild(session);
        if (!isCurrent(session)) return false;
        if (!retired && !session.closed) {
            session.retirement = null;
            session.retrying = false;
            handlers()?.setStartupState("failed");
            return false;
        }
        if (!clients.size) {
            session.retrying = false;
            handlers()?.setStartupState("failed");
            return false;
        }
        await start().completion;
        return true;
    };
    const attach = getHandlers => {
        clients.add(getHandlers);
        lastClient = getHandlers;
        const session = store.backend_session ?? start();
        getHandlers().setStartupState(session.retrying ? "starting" : session.phase);
        startFeeding(session);
        return () => {
            clients.delete(getHandlers);
            if (!clients.size) stopFeeding(store.backend_session);
        };
    };
    return { attach, retry };
};
