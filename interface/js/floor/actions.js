// The operations the Floor's panel sends, in one object: the cards, the Agent tab and the request line take them through their
// environment, so a test can hand them a fake client. Every one is a function of js/api.js; nothing else on this page writes.

import * as api from "../api.js";

export const actions = {
  answer: api.answer,
  release: api.release,
  approve: api.approve,
  reject: api.reject,
  verdict: api.verdict,
  cancel: api.cancel,
  setMode: api.setMode,
  retry: api.retry,
  goAhead: api.goAhead,
  route: api.route,
  handOver: api.handOver,
  pollJob: api.pollJob,
  flows: api.flows,
};
