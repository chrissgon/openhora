// The Lobby's room (WP-9.11): the world of the page (scene/world.js) with the planning floor of the project as its target. This file takes the
// frame's world over for the Lobby's handlers and insets and hands it the world's model (world-model.js) the Lobby worked out; the world is
// the frame's, so the Building takes it over again on Back. Where the engine cannot draw (no WebGL) the panel has everything and the frame
// shows its one line.

import { NoWebGL } from "../scene/engine.js";

/** Take the world over for the Lobby, fitted to the free rectangle the panel leaves. Returns {update(worldModel, label), dispose()}. */
export function mountLobbyScene(frame, panelEl, { onDoor, onSelect } = {}) {
  let engine = null;
  try {
    engine = frame.acquireWorld({
      label: "Lobby, loading",
      getInsets: () => frame.insets(panelEl),
      onOpen: (id) => {
        if (id === "lobby-door") {
          if (onDoor) onDoor();
        } else if (onSelect) {
          onSelect(id);      // the tray, the cabinet, a sheet, the desk, the board, the figure: the tabs' equivalents
        }
      },
      onUnavailable: () => frame.sceneUnavailable(true),
    });
    frame.sceneUnavailable(false);
  } catch (e) {
    if (!(e instanceof NoWebGL)) throw e;
    frame.sceneUnavailable(true);
  }
  const observer = new ResizeObserver(() => { if (engine) engine.refit(); });
  observer.observe(frame.track.el);
  observer.observe(frame.noticeBox);
  observer.observe(panelEl);
  return {
    update(model, label) {
      if (engine) engine.show("world", model, label);
    },
    dispose() {
      observer.disconnect();
      engine = null;   // the scene is the frame's
      frame.sceneUnavailable(false);
    },
    stats() {
      return engine ? engine.stats() : null;
    },
  };
}
