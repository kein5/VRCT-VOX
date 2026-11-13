export const isBackendUpdate = endpoint => ["/run/update_software", "/run/update_cuda_software"].includes(endpoint);

export const expectBackendExit = (session, endpoint) => {
    if (!session || (endpoint !== "/run/shutdown" && !isBackendUpdate(endpoint))) return null;
    const token = { endpoint };
    if (!session.expectedExits.has(endpoint)) session.expectedExits.set(endpoint, new Set());
    session.expectedExits.get(endpoint).add(token);
    return token;
};

export const undoExpectedExit = (session, token) => {
    if (!token) return;
    const tokens = session.expectedExits.get(token.endpoint);
    if (!tokens?.delete(token)) return;
    if (tokens.size === 0) session.expectedExits.delete(token.endpoint);
};

export const rejectExpectedExit = (session, endpoint) => {
    session?.expectedExits.delete(endpoint);
};
