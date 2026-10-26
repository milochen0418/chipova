/**
 * Chipova: co-editing the open file (one Yjs document per file), adapted from Codoc in CAD's
 * yjs_collab.js (itself from codoc_in_md).
 *
 *   1. yjs + y-websocket come from esm.sh; MonacoBinding is vendored (y-monaco@0.1.6, MIT ©
 *      Kevin Jahns) so it uses the page's `window.monaco`.
 *   2. The editor panel (#editor-panel) says which document it shows (data-chip-doc =
 *      <project>-<file>), the ticket that lets this person in (data-chip-ticket), whether they
 *      may only read (data-chip-readonly), who they are for their cursor (data-chip-user-*) and
 *      where the backend is (data-backend). The script connects that document to
 *      /_chipova/yjs/<doc>?t=<ticket> and binds it to the editor; another file means another
 *      document.
 *   3. Remote cursors (HackMD-style): everyone's caret and selection in their colour with a
 *      name tag; `window._chipFollow(peer)` brings someone's caret into view.
 *   4. An editor stays read-only until it is bound (typing before would be lost), and for
 *      viewers always.
 *   5. #chip-sync shows the connection; problems of the selected run (#chip-problems
 *      data-problems) become the editor's markers; `window.chipReveal(file, line, column)` goes
 *      to a line (now, or once that file's editor is bound).
 */
(() => {
  /* ===================== Vendored helpers (lib0 mutex) ===================== */
  const createMutex = () => {
    let token = true;
    return (f, g) => {
      if (token) {
        token = false;
        try { f(); } finally { token = true; }
      } else if (g !== undefined) {
        g();
      }
    };
  };

  /* ===================== Vendored MonacoBinding (y-monaco@0.1.6, MIT) ===================== */

  class RelativeSelection {
    constructor(start, end, direction) {
      this.start = start;
      this.end = end;
      this.direction = direction;
    }
  }

  const _createRelSel = (Y, editor, monacoModel, type) => {
    const sel = editor.getSelection();
    if (sel !== null) {
      const startPos = sel.getStartPosition();
      const endPos = sel.getEndPosition();
      const start = Y.createRelativePositionFromTypeIndex(type, monacoModel.getOffsetAt(startPos));
      const end = Y.createRelativePositionFromTypeIndex(type, monacoModel.getOffsetAt(endPos));
      return new RelativeSelection(start, end, sel.getDirection());
    }
    return null;
  };

  const _relSelToMonaco = (Y, m, editor, type, relSel, doc) => {
    const start = Y.createAbsolutePositionFromRelativePosition(relSel.start, doc);
    const end = Y.createAbsolutePositionFromRelativePosition(relSel.end, doc);
    if (start !== null && end !== null && start.type === type && end.type === type) {
      const model = editor.getModel();
      const sp = model.getPositionAt(start.index);
      const ep = model.getPositionAt(end.index);
      return m.Selection.createWithDirection(sp.lineNumber, sp.column, ep.lineNumber, ep.column, relSel.direction);
    }
    return null;
  };

  /* ===================== Remote cursors (HackMD-style) ===================== */

  const TAG_SHOW_MS = 2000; // a name tag stays up this long after its owner moves
  const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;
  const FALLBACK_COLOR = "#3B82F6";

  const safeColor = (c) => (typeof c === "string" && HEX_COLOR.test(c) ? c : FALLBACK_COLOR);

  const rgba = (hex, alpha) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  };

  /** Dark text on light colours, white text on the others. */
  const tagTextColor = (hex) => {
    const n = parseInt(hex.slice(1), 16);
    const lin = (v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    const lum = 0.2126 * lin(n >> 16) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
    return lum > 0.3 ? "#111827" : "#ffffff";
  };

  const CURSOR_CSS = `
.yRemoteSelection { background-color: ${rgba(FALLBACK_COLOR, 0.3)}; }
.yRemoteSelectionHead {
  position: absolute; height: 100%; box-sizing: border-box; margin-left: -1px;
  border-left: 3px solid ${FALLBACK_COLOR}; color: ${FALLBACK_COLOR}; pointer-events: none;
}
/* A small flag on top of the caret: whose it is stays visible after the name tag fades. */
.yRemoteSelectionHead::before {
  content: ""; position: absolute; top: -3px; left: -5px; width: 7px; height: 7px;
  border-radius: 2px; background: currentColor;
}
.chip-cursor-tag {
  padding: 0 6px; border-radius: 4px 4px 4px 0; white-space: nowrap; pointer-events: none;
  font: 600 11px/16px system-ui, -apple-system, "Segoe UI", sans-serif;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4); opacity: 0; transition: opacity 0.15s;
}
.chip-cursor-tag.is-visible { opacity: 1; }
`;

  let cursorStyleEl = null;

  /** One stylesheet with every remote person's colour, keyed by Yjs clientID. */
  const updateCursorStyles = (states, selfID) => {
    let css = CURSOR_CSS;
    states.forEach((state, id) => {
      if (id === selfID || !Number.isInteger(id)) return;
      const color = safeColor(state.user && state.user.color);
      css += `.yRemoteSelection-${id} { background-color: ${rgba(color, 0.3)}; }\n`;
      css += `.yRemoteSelectionHead-${id} { border-left-color: ${color}; color: ${color}; }\n`;
    });
    if (!cursorStyleEl || !cursorStyleEl.isConnected) {
      cursorStyleEl = document.createElement("style");
      cursorStyleEl.id = "chip-remote-cursors";
      document.head.appendChild(cursorStyleEl);
    }
    if (cursorStyleEl.textContent !== css) cursorStyleEl.textContent = css;
  };

  /** A remote person's name tag: a Monaco content widget just above their caret. */
  class CursorTag {
    constructor(m, clientID) {
      this._m = m;
      this._id = "chip.cursorTag." + clientID;
      this.node = document.createElement("div");
      this.node.className = "chip-cursor-tag";
      this.position = null;
      this.active = false; // moved or typed in the last TAG_SHOW_MS
      this.hovered = false;
      this.timer = 0;
    }

    getId() { return this._id; }

    getDomNode() { return this.node; }

    getPosition() {
      if (!this.position) return null;
      const P = this._m.editor.ContentWidgetPositionPreference;
      return { position: this.position, preference: [P.ABOVE, P.BELOW] };
    }

    refresh() { this.node.classList.toggle("is-visible", this.active || this.hovered); }
  }

  /**
   * Bi-directional binding between a Y.Text and a Monaco ITextModel, with the others' cursors.
   */
  class MonacoBinding {
    constructor(Y, m, ytext, monacoModel, editors, awareness) {
      if (!editors) editors = new Set();
      this.doc = ytext.doc;
      this.ytext = ytext;
      this.monacoModel = monacoModel;
      this.editors = editors;
      this.mux = createMutex();
      this._savedSelections = new Map();
      this._Y = Y;
      this._m = m;

      /* --- save cursor positions before transactions --- */
      this._beforeTransaction = () => {
        this.mux(() => {
          this._savedSelections = new Map();
          editors.forEach((ed) => {
            if (ed.getModel() === monacoModel) {
              const r = _createRelSel(Y, ed, monacoModel, ytext);
              if (r) this._savedSelections.set(ed, r);
            }
          });
        });
      };
      this.doc.on("beforeAllTransactions", this._beforeTransaction);

      /* --- remote cursors: caret/selection decorations + name tags --- */
      this._decorations = new Map();
      this._tags = new Map(); // editor -> Map(clientID -> CursorTag)
      this._spots = new Map(); // editor -> Map(clientID -> { head, start, end, user })
      this._rerenderDecorations = () => {
        if (awareness) updateCursorStyles(awareness.getStates(), this.doc.clientID);
        editors.forEach((editor) => {
          if (awareness && editor.getModel() === monacoModel) {
            const cur = this._decorations.get(editor) || [];
            const next = [];
            const spots = new Map();
            awareness.getStates().forEach((state, clientID) => {
              if (
                clientID !== this.doc.clientID &&
                state.selection != null &&
                state.selection.anchor != null &&
                state.selection.head != null
              ) {
                const aAbs = Y.createAbsolutePositionFromRelativePosition(state.selection.anchor, this.doc);
                const hAbs = Y.createAbsolutePositionFromRelativePosition(state.selection.head, this.doc);
                if (aAbs && hAbs && aAbs.type === ytext && hAbs.type === ytext) {
                  let start, end, after, before;
                  if (aAbs.index < hAbs.index) {
                    start = monacoModel.getPositionAt(aAbs.index);
                    end = monacoModel.getPositionAt(hAbs.index);
                    after = "yRemoteSelectionHead yRemoteSelectionHead-" + clientID;
                    before = null;
                  } else {
                    start = monacoModel.getPositionAt(hAbs.index);
                    end = monacoModel.getPositionAt(aAbs.index);
                    after = null;
                    before = "yRemoteSelectionHead yRemoteSelectionHead-" + clientID;
                  }
                  next.push({
                    range: new m.Range(start.lineNumber, start.column, end.lineNumber, end.column),
                    options: {
                      className: "yRemoteSelection yRemoteSelection-" + clientID,
                      afterContentClassName: after,
                      beforeContentClassName: before,
                    },
                  });
                  spots.set(clientID, { head: monacoModel.getPositionAt(hAbs.index), start, end, user: state.user });
                }
              }
            });
            this._decorations.set(editor, editor.deltaDecorations(cur, next));
            this._spots.set(editor, spots);
            try {
              this._renderTags(editor, spots);
            } catch (err) {
              console.warn("[chip-yjs] cursor tags:", err);
            }
          } else {
            this._decorations.delete(editor);
          }
        });
      };

      /* --- Y.Text → Monaco --- */
      this._ytextObserver = (event) => {
        this.mux(() => {
          let index = 0;
          event.delta.forEach((op) => {
            if (op.retain !== undefined) {
              index += op.retain;
            } else if (op.insert !== undefined) {
              const pos = monacoModel.getPositionAt(index);
              const range = new m.Selection(pos.lineNumber, pos.column, pos.lineNumber, pos.column);
              monacoModel.applyEdits([{ range, text: /** @type {string} */ (op.insert) }]);
              index += op.insert.length;
            } else if (op.delete !== undefined) {
              const pos = monacoModel.getPositionAt(index);
              const endPos = monacoModel.getPositionAt(index + op.delete);
              const range = new m.Selection(pos.lineNumber, pos.column, endPos.lineNumber, endPos.column);
              monacoModel.applyEdits([{ range, text: "" }]);
            }
          });
          this._savedSelections.forEach((rsel, ed) => {
            const sel = _relSelToMonaco(Y, m, ed, ytext, rsel, this.doc);
            if (sel) ed.setSelection(sel);
          });
        });
        this._rerenderDecorations();
      };
      ytext.observe(this._ytextObserver);

      /* --- initial value reconciliation --- */
      {
        const ytv = ytext.toString();
        if (monacoModel.getValue() !== ytv) {
          monacoModel.setValue(ytv);
        }
      }

      /* --- Monaco → Y.Text --- */
      this._monacoChangeHandler = monacoModel.onDidChangeContent((event) => {
        this.mux(() => {
          this.doc.transact(() => {
            event.changes
              .sort((a, b) => b.rangeOffset - a.rangeOffset)
              .forEach((change) => {
                ytext.delete(change.rangeOffset, change.rangeLength);
                ytext.insert(change.rangeOffset, change.text);
              });
          }, this);
        });
      });

      this._monacoDisposeHandler = monacoModel.onWillDispose(() => {
        this.destroy();
      });

      /* --- awareness (cursor broadcast) --- */
      this._listeners = [];
      if (awareness) {
        editors.forEach((editor) => {
          // Our caret and selection, for the others: only while we are in the editor, so
          // someone who clicked in to scroll and went on reading doesn't park a caret there.
          const publishSelection = () => {
            if (editor.getModel() !== monacoModel) return;
            const sel = editor.getSelection();
            if (!sel) return;
            let anchor = monacoModel.getOffsetAt(sel.getStartPosition());
            let head = monacoModel.getOffsetAt(sel.getEndPosition());
            if (sel.getDirection() === m.SelectionDirection.RTL) {
              const tmp = anchor; anchor = head; head = tmp;
            }
            awareness.setLocalStateField("selection", {
              anchor: Y.createRelativePositionFromTypeIndex(ytext, anchor),
              head: Y.createRelativePositionFromTypeIndex(ytext, head),
            });
          };
          const hideSelection = () => {
            try { awareness.setLocalStateField("selection", null); } catch { /* ignore */ }
          };
          this._listeners.push(editor.onDidChangeCursorSelection(() => {
            if (editor.hasTextFocus()) publishSelection();
          }));
          this._listeners.push(editor.onDidFocusEditorText(publishSelection));
          this._listeners.push(editor.onDidBlurEditorText(hideSelection));
          // Hovering someone's caret or selection shows their name tag.
          this._listeners.push(editor.onMouseMove((e) => this._hover(editor, e.target && e.target.position)));
          this._listeners.push(editor.onMouseLeave(() => this._hover(editor, null)));
        });
        // Whoever moved or typed shows their name tag for a moment, as on HackMD.
        this._onAwarenessChange = ({ added, updated }) => {
          this._rerenderDecorations();
          added.concat(updated).forEach((id) => {
            if (id !== this.doc.clientID) this._flashTag(id);
          });
        };
        awareness.on("change", this._onAwarenessChange);
        this.awareness = awareness;
        // Show the cursors that are already there (e.g. after a view-mode switch).
        this._rerenderDecorations();
      }
    }

    _renderTags(editor, spots) {
      let tags = this._tags.get(editor);
      if (!tags) {
        tags = new Map();
        this._tags.set(editor, tags);
      }
      Array.from(tags.keys()).forEach((id) => {
        if (!spots.has(id)) this._removeTag(editor, tags, id);
      });
      spots.forEach(({ head, user }, id) => {
        const name = (user && typeof user.name === "string" && user.name.trim()) || "Guest";
        const color = safeColor(user && user.color);
        let tag = tags.get(id);
        const isNew = !tag;
        if (isNew) {
          tag = new CursorTag(this._m, id);
          tags.set(id, tag);
        }
        if (tag.node.textContent !== name) tag.node.textContent = name;
        tag.node.style.backgroundColor = color;
        tag.node.style.color = tagTextColor(color);
        const moved = !tag.position || tag.position.lineNumber !== head.lineNumber || tag.position.column !== head.column;
        tag.position = { lineNumber: head.lineNumber, column: head.column };
        if (isNew) {
          editor.addContentWidget(tag);
          this._flashTag(id); // a cursor that just appeared here shows its name too
        } else if (moved) {
          editor.layoutContentWidget(tag);
        }
      });
    }

    _removeTag(editor, tags, id) {
      const tag = tags.get(id);
      if (!tag) return;
      clearTimeout(tag.timer);
      try { editor.removeContentWidget(tag); } catch { /* editor already disposed */ }
      tags.delete(id);
    }

    _flashTag(clientID) {
      this._tags.forEach((tags) => {
        const tag = tags.get(clientID);
        if (!tag) return;
        tag.active = true;
        tag.refresh();
        clearTimeout(tag.timer);
        tag.timer = setTimeout(() => {
          tag.active = false;
          tag.refresh();
        }, TAG_SHOW_MS);
      });
    }

    _hover(editor, pos) {
      const tags = this._tags.get(editor);
      if (!tags) return;
      const spots = this._spots.get(editor) || new Map();
      let hit = null;
      if (pos) {
        spots.forEach(({ head, start, end }, id) => {
          if (hit !== null) return;
          const nearCaret = pos.lineNumber === head.lineNumber && Math.abs(pos.column - head.column) <= 1;
          const range = new this._m.Range(start.lineNumber, start.column, end.lineNumber, end.column);
          if (nearCaret || (!range.isEmpty() && range.containsPosition(pos))) hit = id;
        });
      }
      tags.forEach((tag, id) => {
        const hovered = id === hit;
        if (tag.hovered !== hovered) {
          tag.hovered = hovered;
          tag.refresh();
        }
      });
    }

    /** Brings the caret of the person with this peer id into view; false when they are not in
        the editor. */
    follow(peer) {
      let found = false;
      this._spots.forEach((spots, editor) => {
        spots.forEach(({ head, user }, id) => {
          if (found || !user || user.peer !== peer) return;
          found = true;
          editor.revealPositionInCenterIfOutsideViewport(head);
          this._flashTag(id);
        });
      });
      return found;
    }

    destroy() {
      // Once: the model's disposal destroys the binding, and so does the caller that notices
      // the editor is gone (yjs logs an error otherwise).
      if (this._destroyed) return;
      this._destroyed = true;
      try { this._monacoChangeHandler.dispose(); } catch {}
      try { this._monacoDisposeHandler.dispose(); } catch {}
      try { this.ytext.unobserve(this._ytextObserver); } catch {}
      try { this.doc.off("beforeAllTransactions", this._beforeTransaction); } catch {}
      this._listeners.forEach((l) => { try { l.dispose(); } catch {} });
      this._listeners = [];
      this._tags.forEach((tags, editor) => {
        Array.from(tags.keys()).forEach((id) => this._removeTag(editor, tags, id));
      });
      this._tags.clear();
      this._decorations.forEach((ids, editor) => { try { editor.deltaDecorations(ids, []); } catch {} });
      this._decorations.clear();
      if (this.awareness) {
        try { this.awareness.off("change", this._onAwarenessChange); } catch {}
        // This editor is gone: stop showing our caret to the others.
        try { this.awareness.setLocalStateField("selection", null); } catch {}
      }
    }
  }

  /* ===================== Module-level state ===================== */
  let ydoc = null;
  let provider = null;
  let binding = null;
  let boundEditor = null;
  let currentDocId = null;
  let refused = null; // a document the server refused (no access): not retried
  let setupBusy = false;
  let setupErrors = 0;
  const MAX_SETUP_ERRORS = 5;

  let Y = null;
  let WsProvider = null;

  /* ===================== Helpers ===================== */

  const panel = () => document.getElementById("editor-panel");

  const attr = (el, name) => (el ? el.getAttribute("data-" + name) ?? el.getAttribute("data_" + name.replace(/-/g, "_")) : null);

  /** The document on screen: data-chip-doc of the editor panel. */
  const getDocId = () => attr(panel(), "chip-doc") || "";

  const getWsBase = () => {
    const base = attr(panel(), "backend") || window.location.href;
    const url = new URL("/_chipova/yjs", base);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
  };

  const readOnly = () => attr(panel(), "chip-readonly") === "true";

  const getEditor = () => {
    try {
      const eds = window.monaco && window.monaco.editor && window.monaco.editor.getEditors();
      if (!eds || !eds.length) return null;
      const p = panel();
      return eds.find((e) => p && p.contains(e.getContainerDomNode())) || null;
    } catch {
      return null;
    }
  };

  const editorReadyFor = (docId) => getDocId() === docId;

  /** This person's name, colour and peer id for their cursor. */
  const readLocalUser = () => {
    const el = panel();
    if (!el) return null;
    const name = (attr(el, "chip-user-name") || "").trim();
    const color = attr(el, "chip-user-color") || "";
    const peer = attr(el, "chip-user-peer") || "";
    return name ? { name, color: HEX_COLOR.test(color) ? color : "#14B8A6", peer } : null;
  };

  let localCursorStyleEl = null;

  const styleLocalCursor = (color) => {
    const css = `#editor-panel .monaco-editor .cursors-layer .cursor { background-color: ${color} !important; border-color: ${color} !important; }\n`;
    if (!localCursorStyleEl || !localCursorStyleEl.isConnected) {
      localCursorStyleEl = document.createElement("style");
      localCursorStyleEl.id = "chip-local-cursor";
      document.head.appendChild(localCursorStyleEl);
    }
    if (localCursorStyleEl.textContent !== css) localCursorStyleEl.textContent = css;
  };

  const syncLocalUser = () => {
    const user = readLocalUser();
    if (!user) return;
    styleLocalCursor(user.color);
    const awareness = provider && provider.awareness;
    if (!awareness) return;
    const cur = (awareness.getLocalState() || {}).user;
    if (!cur || cur.name !== user.name || cur.color !== user.color || cur.peer !== user.peer) {
      awareness.setLocalStateField("user", user);
    }
  };

  /* ---- the connection, shown in the status bar ---- */
  const STATUS = {
    connected: ["#34d399", "Live: edits reach everyone"],
    connecting: ["#fbbf24", "Connecting…"],
    disconnected: ["#f87171", "Offline: your edits are kept and sent when back"],
    refused: ["#f87171", "No access to this file"],
    idle: ["#64748b", ""],
  };
  let shownStatus = "";
  const showStatus = (status) => {
    const el = document.getElementById("chip-sync");
    if (!el || shownStatus === status + (el.childNodes.length ? "" : "!")) return;
    shownStatus = status;
    const [color, text] = STATUS[status] || STATUS.idle;
    el.setAttribute("data-state", status);
    el.innerHTML = text ? `<span style="width:7px;height:7px;border-radius:9999px;background:${color};display:inline-block"></span>${text}` : "";
  };

  /* ---- problems of the selected run → markers ---- */
  let markersKey = "";
  const applyMarkers = () => {
    const editor = boundEditor;
    const src = document.getElementById("chip-problems");
    if (!editor || !window.monaco || !src) return;
    const path = attr(panel(), "chip-path") || "";
    const json = attr(src, "problems") || "[]";
    const key = path + "|" + json + "|" + (editor.getModel() ? editor.getModel().id : "");
    if (key === markersKey) return;
    markersKey = key;
    let list = [];
    try { list = JSON.parse(json); } catch { list = []; }
    const m = window.monaco;
    const sev = { error: m.MarkerSeverity.Error, warning: m.MarkerSeverity.Warning, info: m.MarkerSeverity.Info };
    const markers = list
      .filter((p) => p.file === path && p.line > 0)
      .map((p) => ({
        severity: sev[p.severity] || m.MarkerSeverity.Info,
        message: (p.code ? p.code + ": " : "") + p.message,
        startLineNumber: p.line, startColumn: p.column || 1,
        endLineNumber: p.line, endColumn: p.column ? p.column + 1 : 1000,
      }));
    try { m.editor.setModelMarkers(editor.getModel(), "chipova", markers); } catch {}
  };

  /* ---- the lines people commented on: a mark beside them ---- */
  let commentKey = "";
  let commentDecorations = [];
  const applyCommentMarks = () => {
    const editor = boundEditor;
    const src = document.getElementById("chip-comments");
    if (!editor || !window.monaco || !src) return;
    const path = attr(panel(), "chip-path") || "";
    const json = attr(src, "lines") || "{}";
    const key = path + "|" + json + "|" + (editor.getModel() ? editor.getModel().id : "");
    if (key === commentKey) return;
    commentKey = key;
    let lines = [];
    try { lines = (JSON.parse(json) || {})[path] || []; } catch { lines = []; }
    const m = window.monaco;
    try {
      commentDecorations = editor.deltaDecorations(commentDecorations, lines.map((n) => ({
        range: new m.Range(n, 1, n, 1),
        options: { isWholeLine: true, linesDecorationsClassName: "chip-comment-mark", hoverMessage: { value: "Commented: see Comments" } },
      })));
    } catch {}
  };
  const markStyle = document.createElement("style");
  markStyle.textContent = ".chip-comment-mark { background: #f59e0b; width: 4px !important; margin-left: 3px; border-radius: 2px; }";
  document.head.appendChild(markStyle);

  /** The line of the open file's caret (for a comment on it). */
  window.chipCursorLine = () => {
    try { return boundEditor ? boundEditor.getPosition().lineNumber : 1; } catch { return 1; }
  };

  /* ---- going to a line ---- */
  let pendingReveal = null;
  window.chipReveal = (fileId, line, column) => {
    pendingReveal = { fileId, line: line || 1, column: column || 1, at: Date.now() };
    doReveal();
  };
  const doReveal = () => {
    if (!pendingReveal || !boundEditor) return;
    if (Date.now() - pendingReveal.at > 15000) { pendingReveal = null; return; }
    if (attr(panel(), "chip-file") !== pendingReveal.fileId) return;
    const { line, column } = pendingReveal;
    pendingReveal = null;
    try {
      boundEditor.revealLineInCenter(line);
      boundEditor.setPosition({ lineNumber: line, column });
      boundEditor.focus();
    } catch {}
  };

  /* ===================== Lifecycle ===================== */

  const destroyBinding = () => {
    if (binding) {
      try { binding.destroy(); } catch {}
      binding = null;
    }
    boundEditor = null;
    markersKey = "";
    commentKey = "";
    commentDecorations = [];
    markBound("");
  };

  const destroyAll = () => {
    destroyBinding();
    if (provider) {
      try { provider.awareness.setLocalState(null); } catch {}
      try { provider.destroy(); } catch {}
      provider = null;
    }
    if (ydoc) {
      try { ydoc.destroy(); } catch {}
      ydoc = null;
    }
    window._chipYjs = null;
    currentDocId = null;
  };

  window._chipFollow = (peer) => (binding ? binding.follow(peer) : false);

  const ensureModules = async () => {
    if (Y) return;
    const CDN = "https://esm.sh";
    const YJS_VER = "yjs@13.6.18";
    const [yMod, wsMod] = await Promise.all([
      import(`${CDN}/${YJS_VER}`),
      import(`${CDN}/y-websocket@2.0.4?deps=${YJS_VER}`),
    ]);
    Y = yMod;
    WsProvider = wsMod.WebsocketProvider;
  };

  const setup = async (docId) => {
    if (setupBusy) return;
    if (currentDocId === docId && ydoc) return;
    if (setupErrors >= MAX_SETUP_ERRORS || refused === docId) return;
    setupBusy = true;
    try {
      destroyAll();
      await ensureModules();
      currentDocId = docId;
      ydoc = new Y.Doc();
      const ytext = ydoc.getText("monaco");
      const ticket = attr(panel(), "chip-ticket") || "";
      const prov = new WsProvider(getWsBase(), docId, ydoc, { params: { t: ticket }, resyncInterval: 10000 });
      provider = prov;
      showStatus("connecting");
      prov.on("status", ({ status }) => {
        showStatus(status === "connected" ? "connected" : status === "connecting" ? "connecting" : "disconnected");
        if (status !== "connected" || !prov.ws) return;
        try { prov.ws.send(new Uint8Array([3])); } catch {}
      });
      prov.on("connection-close", (event) => {
        // 4401/4403: no ticket, or no access. 4404/4410: the file is gone. Not retried.
        if (event && event.code >= 4400 && event.code < 4500) {
          refused = docId;
          showStatus("refused");
          try { prov.disconnect(); } catch {}
        }
      });
      syncLocalUser();
      await new Promise((resolve) => {
        if (provider.synced) { resolve(); return; }
        const onSync = (ev) => {
          if (ev && ev.synced !== undefined ? ev.synced : true) {
            provider.off("synced", onSync);
            resolve();
          }
        };
        provider.on("synced", onSync);
        setTimeout(() => { provider && provider.off("synced", onSync); resolve(); }, 3000);
      });
      window._chipYjs = { ytext, provider, ydoc, docId };
      setupErrors = 0;
    } catch (err) {
      setupErrors++;
      console.error("[chip-yjs] setup error (" + setupErrors + "/" + MAX_SETUP_ERRORS + "):", err);
    } finally {
      setupBusy = false;
    }
  };

  const HOLD_MS = 10000;
  let held = null;
  let heldSince = 0;

  const release = (editor) => {
    if (!held) return;
    try { held.updateOptions({ readOnly: readOnly() }); } catch {}
    held = null;
  };

  const holdUntilBound = (editor) => {
    if (editor.__chipFreeAt !== undefined) return;
    if (held !== editor) {
      release();
      held = editor;
      heldSince = Date.now();
      try { editor.updateOptions({ readOnly: true }); } catch {}
      return;
    }
    if (setupErrors > 0 || Date.now() - heldSince > HOLD_MS) {
      const model = editor.getModel();
      editor.__chipFreeAt = model ? model.getVersionId() : 0;
      release();
    }
  };

  /** Every editor in the panel starts read-only, the moment Monaco makes it: typing into it
      before it is bound to the shared document would be lost when it binds. */
  let createHooked = false;
  const hookCreate = () => {
    if (createHooked || !window.monaco || !window.monaco.editor || !window.monaco.editor.onDidCreateEditor) return;
    createHooked = true;
    window.monaco.editor.onDidCreateEditor((ed) => {
      setTimeout(() => {
        const p = panel();
        try {
          if (p && p.contains(ed.getContainerDomNode()) && ed !== boundEditor) ed.updateOptions({ readOnly: true });
        } catch {}
      }, 0);
    });
  };

  const markBound = (docId) => {
    const p = panel();
    if (!p) return;
    if (docId) p.setAttribute("data-chip-bound", docId);
    else p.removeAttribute("data-chip-bound");
  };

  const tryRebind = () => {
    if (!window._chipYjs || !currentDocId || !Y) return;
    if (window._chipYjs.docId !== currentDocId || !editorReadyFor(currentDocId)) return;
    const editor = getEditor();
    if (!editor) return;
    destroyBinding();
    const { ytext, provider: prov, ydoc: yd } = window._chipYjs;
    const model = editor.getModel();
    if (!model || !ytext) return;
    try {
      if (model.getEOL() !== "\n") model.setEOL(window.monaco.editor.EndOfLineSequence.LF);
    } catch {}
    const typedMeanwhile = editor.__chipFreeAt !== undefined && model.getVersionId() !== editor.__chipFreeAt;
    if (typedMeanwhile && yd && !readOnly()) {
      const content = model.getValue();
      if (content) {
        yd.transact(() => {
          if (ytext.length) ytext.delete(0, ytext.length);
          ytext.insert(0, content);
        });
      }
    }
    binding = new MonacoBinding(Y, window.monaco, ytext, model, new Set([editor]), prov ? prov.awareness : null);
    boundEditor = editor;
    release(editor);
    try { editor.updateOptions({ readOnly: readOnly() }); } catch {}
    markBound(currentDocId);
    doReveal();
  };

  /* ===================== Polling loop ===================== */

  const poll = () => {
    hookCreate();
    const docId = getDocId();
    if (!docId) {
      if (currentDocId && !setupBusy) destroyAll();
      if (!panel()) showStatus("idle");
      return;
    }
    const editor = getEditor();
    if (binding && editor !== boundEditor) destroyBinding();
    if (editor && !binding) holdUntilBound(editor);
    if (docId !== currentDocId) {
      setup(docId);
      return;
    }
    syncLocalUser();
    if (editor && !binding) tryRebind();
    if (binding) {
      applyMarkers();
      applyCommentMarks();
      doReveal();
      try {
        const ro = readOnly();
        if (boundEditor.getOption(window.monaco.editor.EditorOption.readOnly) !== ro) boundEditor.updateOptions({ readOnly: ro });
      } catch {}
    }
  };

  const start = () => {
    setInterval(poll, 400);
    poll();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  window.addEventListener("beforeunload", destroyAll);
  window.addEventListener("pagehide", destroyAll);
})();
