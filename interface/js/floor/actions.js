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
  mediaPipeline: api.mediaPipeline,
  artifacts: api.artifacts,
  artifact: api.artifact,
  captionsRead: api.captionsRead,
  captionsEdit: api.captionsEdit,
  captionsDone: api.captionsDone,
  prepareAgain: api.prepareAgain,
  mediaList: api.mediaList,
  uploadMedia: api.uploadMedia,
  videoCard: api.videoCard,
  videoApprove: api.videoApprove,
  videoSendBack: api.videoSendBack,
  videoRaw: api.videoRaw,
  videoCover: api.videoCover,
  videoDownload: api.videoDownload,
  pollJob: api.pollJob,
  flows: api.flows,
};
