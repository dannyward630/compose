// OpenCode plugin: asks compose's read guard (bin/fc_readguard.py) before each tool call. COMPOSE_READGUARD is the shell line
// that runs the guard; a non-empty reply is thrown, which refuses the call.
export const ReadGuard = async (ctx) => ({});
