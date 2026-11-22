import { randomUUID } from 'node:crypto';

export function connection(env = process.env) {
  const url = new URL(env.CLAWREFLEX_URL || 'http://127.0.0.1:8787');
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('CLAWREFLEX_URL must be a loopback HTTP origin');
  }
  if (!env.CLAWREFLEX_TOKEN || env.CLAWREFLEX_TOKEN.length < 24) throw new Error('CLAWREFLEX_TOKEN must contain at least 24 characters');
  return { origin: url.origin, token: env.CLAWREFLEX_TOKEN };
}

export async function request(path, body, { env = process.env, fetcher = fetch } = {}) {
  const { origin, token } = connection(env);
  const response = await fetcher(origin + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(30000),
  });
  const details = await response.json();
  return { details, ok: response.ok };
}

export function card(state) {
  const patch = state.patch || {};
  const verification = patch.verification || {};
  const probe = state.probe || {};
  const id = state.id || state.run_id || '';
  const suffix = id ? ' ' + id : '';
  const evidence = probe.ok ? 'RED confirmed; independent reference passed' : 'RED not confirmed';
  const tests = verification.tests_run ?? 'unavailable';
  const elapsed = state.elapsed_s === undefined ? 'unavailable' : state.elapsed_s + ' s';
  const status = state.status || state.state || 'unknown';
  const lines = [`ClawReflex · ${state.title || state.path || 'verified repair'}`, `State: ${status}`, evidence,
    `GREEN tests: ${tests} · elapsed: ${elapsed}`, `Applied to target: ${state.applied === true ? 'yes' : 'no'}`];
  if (state['patch.diff']) lines.push('Diff:\n' + String(state['patch.diff']).slice(0, 6000));
  lines.push(`Review: /clawreflex status${suffix}`, `Apply: /clawreflex apply${suffix}`, `Revert: /clawreflex revert${suffix}`, `Cancel: /clawreflex cancel${suffix}`);
  return { text: lines.join('\n'), continueAgent: false };
}

function runPath(id, action) {
  if (id && !/^[a-zA-Z0-9_-]{1,128}$/.test(id)) throw new Error('invalid run ID');
  return id ? `/runs/${encodeURIComponent(id)}/${action}` : `/${action}`;
}

export default {
  id: 'clawreflex', name: 'ClawReflex',
  register(api) {
    for (const [name, description, properties] of [
      ['clawreflex_probe', 'Prove assertion RED and independent reference GREEN in the sandbox. Import only unittest and app.', { test_source: { type: 'string', maxLength: 6000 } }],
      ['clawreflex_patch', 'Verify the complete Python repair against exploit, regression and held-out tests. Proposes by default; never claim it was applied unless the receipt says so.', { source: { type: 'string', maxLength: 12000 }, summary: { type: 'string', maxLength: 240 } }],
    ]) {
      api.registerTool({ name, description, parameters: { type: 'object', properties: { ...properties, run_id: { type: 'string', maxLength: 128 } }, required: Object.keys(properties), additionalProperties: false },
        async execute(_id, params) {
          try {
            const { run_id, ...body } = params;
            const { details, ok } = await request(runPath(run_id, 'tool/' + name), body);
            return { content: [{ type: 'text', text: JSON.stringify(details) }], details, isError: !ok };
          } catch { return { content: [{ type: 'text', text: 'ClawReflex request failed. Check the loopback server, token and local logs.' }], isError: true }; }
        },
      }, { optional: true });
    }
    if (typeof api.registerCommand === 'function') api.registerCommand({
      name: 'clawreflex', description: 'Review repair evidence or explicitly apply, revert or cancel a run.', acceptsArgs: true, requireAuth: true,
      async handler(ctx) {
        try {
          const [action = 'status', id, extra] = (ctx.args || '').trim().split(/\s+/).filter(Boolean);
          if (extra || !['status', 'history', 'apply', 'revert', 'cancel'].includes(action)) return { text: 'Usage: /clawreflex status|history|apply|revert|cancel [run-id]', continueAgent: false };
          if (action === 'status' || action === 'history') {
            const { details, ok } = await request(id ? runPath(id, 'state') : '/state');
            if (!ok) return { text: 'ClawReflex state unavailable.', continueAgent: false };
            if (Array.isArray(details.runs)) return { text: details.runs.map(run => card(run).text).join('\n\n') || 'No runs yet.', continueAgent: false };
            return card(details);
          }
          // Mutation commands bypass the model and are only executed on an authorized user command.
          const { details, ok } = await request(runPath(id, 'action/' + action), { idempotency_key: randomUUID() });
          return { text: JSON.stringify({ action, ok, ...details }), continueAgent: false };
        } catch { return { text: 'ClawReflex action failed. No success is implied; inspect the local run receipt.', continueAgent: false }; }
      },
    });
  },
};
